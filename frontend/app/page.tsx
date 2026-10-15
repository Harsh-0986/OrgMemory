"use client";

/**
 * OrgMemory, laid out as an assessment document rather than a dashboard.
 *
 * Structure: a masthead, the question, then a two-column report — the answer
 * and its supporting logs on the left, the graph and the reasoning trace on the
 * right. Evidence spans the full width beneath, because it is the widest and
 * the most reference-like material.
 *
 * Selection is one piece of shared state. Clicking a citation in the answer, a
 * chip in the evidence panel, a row in the blast radius, or a node in the graph
 * all focus the same entity, which is what makes a claim traceable in one click.
 */

import { useCallback, useEffect, useMemo, useSyncExternalStore, useState } from "react";
import AnswerPanel from "@/components/AnswerPanel";
import EvidencePanel from "@/components/EvidencePanel";
import GraphCanvas from "@/components/GraphCanvas";
import HistoryList from "@/components/HistoryList";
import ImpactList from "@/components/ImpactList";
import StepsTimeline from "@/components/StepsTimeline";
import { ApiRequestError, api } from "@/lib/api";
import { EXAMPLE_QUESTIONS } from "@/lib/examples";
import type {
  Edge,
  GraphOverview,
  InvestigationResponse,
  InvestigationSummary,
  NodeRef,
} from "@/lib/types";

type Theme = "light" | "dark";

/**
 * The theme lives on the document element - an inline script in the layout sets
 * it before first paint - which makes it an external store rather than React
 * state. `useSyncExternalStore` reads it without mirroring it through an effect,
 * and without a hydration mismatch on the toggle label.
 */
const THEME_EVENT = "orgmemory-theme";

const themeStore = {
  subscribe(callback: () => void) {
    window.addEventListener(THEME_EVENT, callback);
    return () => window.removeEventListener(THEME_EVENT, callback);
  },
  getSnapshot(): Theme {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  },
  getServerSnapshot(): Theme {
    return "light";
  },
};

export default function Dashboard() {
  const [question, setQuestion] = useState(EXAMPLE_QUESTIONS[0].question);
  const [result, setResult] = useState<InvestigationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<InvestigationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [health, setHealth] = useState<{ graph_connected: boolean } | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const theme = useSyncExternalStore(
    themeStore.subscribe,
    themeStore.getSnapshot,
    themeStore.getServerSnapshot,
  );

  const refreshHistory = useCallback(async () => {
    try {
      const data = await api.history(20);
      setHistory(data.investigations);
    } catch {
      // A history failure must not take the dashboard down.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    // State updates live inside the promise callbacks, never synchronously in
    // the effect body, so mounting does not cascade renders.
    void api
      .history(20)
      .then((d) => setHistory(d.investigations))
      .catch(() => undefined)
      .finally(() => setHistoryLoading(false));

    void api
      .health()
      .then(setHealth)
      .catch(() => setHealth({ graph_connected: false }));

    void api
      .overview()
      .then(setOverview)
      .catch(() => setOverview(null));
  }, []);

  const toggleTheme = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("orgmemory-theme", next);
    } catch {
      // Private browsing; the in-session choice still applies.
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, [theme]);

  const run = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (trimmed.length < 8) {
        setError("Ask a question of at least 8 characters.");
        return;
      }
      setLoading(true);
      setError(null);
      setHighlightedId(null);
      setResult(null);

      try {
        const data = await api.investigate(trimmed);
        setResult(data);
        if (data.error) setError(data.error);
        void refreshHistory();
      } catch (err) {
        setError(
          err instanceof ApiRequestError
            ? err.message
            : "The investigation failed unexpectedly.",
        );
      } finally {
        setLoading(false);
      }
    },
    [refreshHistory],
  );

  const select = useCallback((id: string | null) => {
    setHighlightedId(id === "" ? null : id);
  }, []);

  /** Impacted services, shared dependencies and cited entities for the graph. */
  const graphData = useMemo(() => {
    if (!result) return { nodes: [] as NodeRef[], edges: [] as Edge[] };

    const nodes = new Map<string, NodeRef>();
    const add = (node: NodeRef) => {
      if (!nodes.has(node.id)) nodes.set(node.id, node);
    };

    result.impacted_services.forEach((item) => add(item.service));
    result.shared_dependencies.forEach((dep) =>
      add({
        id: dep.id,
        type: "Service",
        name: dep.name,
        properties: { criticality: dep.criticality ?? "" },
      }),
    );
    Object.values(result.owners).forEach((people) => people.forEach(add));
    result.evidence.forEach((record) => record.entities.forEach(add));

    const edges: Edge[] = [];
    const seen = new Set<string>();
    const addEdge = (edge: Edge) => {
      const key = `${edge.type}:${edge.from_id}->${edge.to_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        edges.push(edge);
      }
    };

    // The subject of the question is the graph's root.
    const rootId = result.impacted_services[0]?.service.id;
    if (rootId) {
      result.impacted_services.forEach((item) =>
        addEdge({
          type: "DEPENDS_ON",
          from_id: item.service.id,
          from_type: "Service",
          to_id: rootId,
          to_type: "Service",
        }),
      );
    }

    result.impacted_services.forEach((item) =>
      item.owners.forEach((owner) =>
        addEdge({
          type: "OWNS",
          from_id: owner.id,
          from_type: "Person",
          to_id: item.service.id,
          to_type: "Service",
        }),
      ),
    );

    result.graph_paths.forEach((path) => {
      path.edges.forEach(addEdge);
      path.nodes.forEach(add);
    });

    return { nodes: Array.from(nodes.values()), edges };
  }, [result]);

  /** Every id the answer is allowed to cite. */
  const knownIds = useMemo(() => {
    const ids = new Set<string>();
    result?.evidence.forEach((record) => {
      record.source_ids.forEach((id) => ids.add(id));
      record.entities.forEach((node) => ids.add(node.id));
    });
    result?.impacted_services.forEach((item) => ids.add(item.service.id));
    result?.cited_ids.forEach((id) => ids.add(id));
    return ids;
  }, [result]);

  const critique = result?.critique;
  const connected = health?.graph_connected ?? false;

  return (
    <div className="min-h-screen bg-page text-ink">
      {/* Masthead */}
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-[1400px] items-baseline justify-between gap-6 px-6 py-4">
          <div className="flex items-baseline gap-3">
            <h1 className="font-ui text-[1.05rem] font-semibold tracking-tight">OrgMemory</h1>
            <span className="font-prose text-sm italic text-ink-faint">
              your company&rsquo;s knowledge, connected and explainable
            </span>
          </div>

          <div className="flex items-center gap-4">
            {overview && (
              <span className="font-mono text-[0.7rem] text-ink-faint">
                {overview.total_nodes} nodes · {overview.total_relationships} edges
              </span>
            )}
            <span
              className={[
                "font-ui text-[0.72rem]",
                connected ? "text-verify" : "text-signal",
              ].join(" ")}
            >
              {connected ? "graph connected" : "graph unavailable"}
            </span>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              className="border border-rule px-2 py-1 font-mono text-[0.7rem] text-ink-soft transition hover:border-ink hover:text-ink"
            >
              {theme === "dark" ? "light" : "dark"}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 pb-20">
        {/* Ask */}
        <section className="border-b border-rule py-8">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(question);
            }}
            className="flex flex-col gap-4 sm:flex-row sm:items-end"
          >
            <label className="flex-1">
              <span className="mb-2 block font-ui text-[0.8rem] text-ink-soft">
                What do you need to know?
              </span>
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about your engineering organisation…"
                aria-label="Investigation question"
                className="w-full border border-rule bg-page-raised px-4 py-3 font-prose text-[0.95rem] text-ink outline-none transition placeholder:text-ink-faint focus:border-link"
              />
            </label>
            <button
              type="submit"
              disabled={loading}
              className="border border-ink bg-ink px-6 py-3 font-ui text-sm font-medium text-page transition hover:bg-transparent hover:text-ink disabled:cursor-not-allowed disabled:border-rule disabled:bg-transparent disabled:text-ink-faint"
            >
              {loading ? "Investigating…" : "Investigate"}
            </button>
          </form>

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example.label}
                type="button"
                title={example.hint}
                onClick={() => {
                  setQuestion(example.question);
                  void run(example.question);
                }}
                className="group font-ui text-[0.82rem] text-ink-faint transition hover:text-ink"
              >
                <span
                  className={`underline decoration-dotted underline-offset-4 group-hover:decoration-solid ${
                    example.primary ? "text-link" : ""
                  }`}
                >
                  {example.label}
                </span>
              </button>
            ))}
          </div>
        </section>

        {error && (
          <div className="mt-6 border-l-2 border-signal bg-signal-wash px-4 py-3 font-ui text-sm text-signal">
            {error}
          </div>
        )}

        {loading && (
          <div className="mt-10 border-l-2 border-link pl-5">
            <p className="font-prose text-[0.95rem] text-ink-soft">
              Traversing the knowledge graph…
            </p>
            <ul className="mt-3 space-y-1.5">
              {[
                "Classifying the question",
                "Resolving services",
                "Walking dependencies",
                "Checking claims against evidence",
              ].map((label) => (
                <li key={label} className="flex items-center gap-2.5 font-ui text-xs text-ink-faint">
                  <span className="h-1 w-1 animate-pulse rounded-full bg-link" />
                  {label}
                </li>
              ))}
            </ul>
          </div>
        )}

        {!loading && !result && !error && (
          <section className="py-24">
            <h2 className="max-w-[30ch] font-prose text-3xl leading-tight text-ink">
              Ask a hard question about your engineering organisation.
            </h2>
            <p className="mt-5 max-w-[62ch] font-prose text-[0.98rem] leading-relaxed text-ink-soft">
              OrgMemory traverses people, services, projects, incidents, decisions and
              documents to answer it — then cites the graph record behind every material
              claim, and tells you plainly when the graph does not know something. Start
              with the primary demo above.
            </p>
          </section>
        )}

        {result && (
          <>
            <div className="grid gap-x-12 gap-y-10 py-10 lg:grid-cols-[minmax(0,1fr)_380px]">
              {/* ---- The report ---- */}
              <div className="min-w-0 space-y-10">
                <section>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-rule pb-2">
                    <h2 className="font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                      Answer
                    </h2>
                    <div className="flex flex-wrap items-center gap-x-4 font-mono text-[0.68rem]">
                      <span className="text-ink-faint">{result.intent}</span>
                      <span className="text-ink-faint">confidence {result.confidence}</span>
                      {critique && (
                        <span
                          className={
                            critique.verdict === "pass" ? "text-verify" : "text-signal"
                          }
                        >
                          critic {critique.verdict}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-5 max-w-[68ch]">
                    <AnswerPanel
                      answer={result.answer}
                      knownIds={knownIds}
                      highlightedId={highlightedId}
                      onSelect={select}
                    />
                  </div>

                  <p className="mt-6 max-w-[68ch] border-t border-rule-soft pt-3 font-ui text-[0.72rem] leading-relaxed text-ink-faint">
                    Blue citations were returned by the graph; red ones were not, and are
                    flagged as unverified. Suggested actions are advisory and need human
                    review.
                  </p>
                </section>

                {/* Unknowns get first-class treatment. */}
                {critique && critique.missing_evidence.length > 0 && (
                  <section className="border-l-2 border-signal bg-signal-wash px-4 py-3">
                    <h3 className="font-ui text-[0.78rem] font-semibold text-signal">
                      What the graph does not record
                    </h3>
                    <ul className="mt-2 space-y-1">
                      {critique.missing_evidence.map((gap) => (
                        <li key={gap} className="font-ui text-xs leading-relaxed text-signal/90">
                          {gap}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>

              {/* ---- The figures ---- */}
              <aside className="min-w-0 space-y-10">
                <section>
                  <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                    Blast radius
                  </h2>
                  <div className="mt-4">
                    <ImpactList
                      impacted={result.impacted_services}
                      highlightedId={highlightedId}
                      onSelect={select}
                    />
                  </div>
                </section>

                <section>
                  <div className="flex items-baseline justify-between">
                    <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                      Dependency graph
                    </h2>
                    {highlightedId && (
                      <button
                        type="button"
                        onClick={() => setHighlightedId(null)}
                        className="font-ui text-[0.7rem] text-link hover:underline"
                      >
                        clear focus
                      </button>
                    )}
                  </div>
                  <div className="mt-4 overflow-hidden border border-rule">
                    <GraphCanvas
                      nodes={graphData.nodes}
                      edges={graphData.edges}
                      paths={result.graph_paths}
                      highlightedId={highlightedId}
                      onSelect={select}
                      height={380}
                    />
                  </div>
                </section>

                {result.recommendations.length > 0 && (
                  <section>
                    <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                      Suggested next steps
                    </h2>
                    <ol className="mt-4 space-y-4">
                      {result.recommendations.map((rec, i) => (
                        <li key={i}>
                          <p className="font-ui text-[0.85rem] leading-relaxed text-ink">
                            <span className="mr-1.5 font-mono text-[0.7rem] text-ink-faint">
                              {String(i + 1).padStart(2, "0")}
                            </span>
                            {rec.action}
                          </p>
                          <p className="mt-1 font-prose text-sm leading-relaxed text-ink-soft">
                            {rec.rationale}
                          </p>
                          {rec.suggested_reviewers.length > 0 && (
                            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                              {rec.suggested_reviewers.slice(0, 6).map((person) => (
                                <button
                                  key={person.id}
                                  type="button"
                                  onClick={() => select(person.id)}
                                  className="font-ui text-[0.75rem] text-link underline decoration-dotted underline-offset-2 hover:decoration-solid"
                                >
                                  {person.name}
                                </button>
                              ))}
                            </div>
                          )}
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                {result.recalled_investigations.length > 0 && (
                  <section>
                    <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                      Recalled from earlier
                    </h2>
                    <ul className="mt-4 space-y-3">
                      {result.recalled_investigations.map((item) => (
                        <li key={item.id} className="border-l border-rule pl-3">
                          <p className="font-ui text-xs leading-relaxed text-ink-soft">
                            {item.question}
                          </p>
                          <p className="mt-0.5 font-mono text-[0.65rem] text-ink-faint">
                            {item.id}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section>
                  <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                    Reasoning trace
                  </h2>
                  <div className="mt-4">
                    <StepsTimeline steps={result.steps} />
                  </div>
                </section>

                <section>
                  <h2 className="border-b border-rule pb-2 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                    Earlier investigations
                  </h2>
                  <div className="mt-4">
                    <HistoryList
                      items={history}
                      activeId={result.investigation_id}
                      loading={historyLoading}
                      onSelect={(q) => {
                        setQuestion(q);
                        void run(q);
                      }}
                    />
                  </div>
                </section>
              </aside>
            </div>

            {/* Evidence spans the width — it is reference material. */}
            <section className="border-t border-rule pt-8">
              <h2 className="mb-5 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
                Evidence
              </h2>
              <EvidencePanel
                evidence={result.evidence}
                incidents={result.incidents}
                decisions={result.decisions}
                documents={result.documents}
                highlightedId={highlightedId}
                onSelect={select}
              />
            </section>
          </>
        )}
      </main>
    </div>
  );
}