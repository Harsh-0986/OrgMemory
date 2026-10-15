"use client";

/**
 * OrgMemory dashboard.
 *
 * One question in, one investigation out: the answer, the evidence behind it,
 * the dependency graph that produced it, and the reasoning trace. Selection is
 * shared state - clicking a citation in the answer, a chip in the evidence
 * panel, a row in the impact list, or a node in the graph all focus the same
 * thing, which is what makes a claim traceable in one click.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
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

export default function Dashboard() {
  const [question, setQuestion] = useState(EXAMPLE_QUESTIONS[0].question);
  const [result, setResult] = useState<InvestigationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<InvestigationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [health, setHealth] = useState<{ status: string; graph_connected: boolean } | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);

  const refreshHistory = useCallback(async () => {
    try {
      const data = await api.history(20);
      setHistory(data.investigations);
    } catch {
      // A history failure must not break the dashboard.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    // State updates live inside the promise callbacks, never synchronously in
    // the effect body, so mounting does not cascade renders.
    void api
      .history(20)
      .then((data) => setHistory(data.investigations))
      .catch(() => undefined)
      .finally(() => setHistoryLoading(false));

    void api
      .health()
      .then(setHealth)
      .catch(() => setHealth({ status: "unreachable", graph_connected: false }));

    void api
      .overview()
      .then(setOverview)
      .catch(() => setOverview(null));
  }, []);

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

  /** Union of impacted services and evidence entities for the graph. */
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

    // Owner and depends-on edges reconstructed from the returned structure.
    const edges: Edge[] = [];
    const seen = new Set<string>();
    const addEdge = (edge: Edge) => {
      const key = `${edge.type}:${edge.from_id}->${edge.to_id}`;
      if (!seen.has(key)) {
        seen.add(key);
        edges.push(edge);
      }
    };

    result.impacted_services.forEach((item) => {
      addEdge({
        type: "DEPENDS_ON",
        from_id: item.service.id,
        from_type: "Service",
        to_id: result.impacted_services[0]?.service.id ?? item.service.id,
        to_type: "Service",
      });
      item.owners.forEach((owner) =>
        addEdge({
          type: "OWNS",
          from_id: owner.id,
          from_type: "Person",
          to_id: item.service.id,
          to_type: "Service",
        }),
      );
    });

    result.graph_paths.forEach((path) => {
      path.edges.forEach((edge) => addEdge(edge));
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

  const graphPaths = result?.graph_paths ?? [];
  const critique = result?.critique;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-slate-100">
              OrgMemory
            </h1>
            <p className="text-xs text-slate-500">
              Your company&apos;s knowledge, connected and explainable.
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            {overview && (
              <span className="text-slate-500">
                {overview.total_nodes} nodes · {overview.total_relationships} relationships
              </span>
            )}
            {health && (
              <span
                className={[
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1",
                  health.graph_connected
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                    : "border-rose-500/40 bg-rose-500/10 text-rose-300",
                ].join(" ")}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    health.graph_connected ? "bg-emerald-400" : "bg-rose-400"
                  }`}
                />
                {health.graph_connected ? "Graph connected" : "Graph unavailable"}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-6">
        {/* Ask */}
        <section className="mb-6">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(question);
            }}
            className="flex flex-col gap-3 sm:flex-row"
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your engineering organisation…"
              aria-label="Investigation question"
              className="flex-1 rounded-lg border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-sky-500"
            />
            <button
              type="submit"
              disabled={loading}
              className="rounded-lg bg-sky-500 px-6 py-3 text-sm font-medium text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-500"
            >
              {loading ? "Investigating…" : "Investigate"}
            </button>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example.label}
                type="button"
                title={example.hint}
                onClick={() => {
                  setQuestion(example.question);
                  void run(example.question);
                }}
                className={[
                  "rounded-full border px-3 py-1 text-xs transition",
                  example.primary
                    ? "border-sky-500/50 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20"
                    : "border-slate-800 bg-slate-900/60 text-slate-400 hover:border-slate-700 hover:text-slate-200",
                ].join(" ")}
              >
                {example.label}
              </button>
            ))}
          </div>
        </section>

        {error && (
          <div className="mb-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        {loading && (
          <div className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-6">
            <p className="text-sm text-slate-300">Traversing the knowledge graph…</p>
            <div className="mt-3 space-y-2">
              {["Classifying the question", "Resolving services", "Walking dependencies", "Checking evidence"].map(
                (label) => (
                  <div key={label} className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sky-400" />
                    {label}
                  </div>
                ),
              )}
            </div>
          </div>
        )}

        {!loading && !result && !error && (
          <div className="rounded-xl border border-dashed border-slate-800 px-6 py-16 text-center">
            <h2 className="text-base font-medium text-slate-300">
              Ask a question to begin an investigation
            </h2>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
              OrgMemory traverses people, services, projects, incidents, decisions and
              documents to answer questions about your engineering organisation — and cites
              the graph records behind every material claim. Start with the primary demo
              above.
            </p>
          </div>
        )}

        {result && (
          <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
            <div className="space-y-6">
              {/* Answer */}
              <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                  <h2 className="text-sm font-semibold text-slate-200">Answer</h2>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge label={`intent: ${result.intent}`} tone="slate" />
                    <Badge label={`confidence: ${result.confidence}`} tone={result.confidence === "high" ? "emerald" : "slate"} />
                    {critique && (
                      <Badge
                        label={`critic: ${critique.verdict}`}
                        tone={critique.verdict === "pass" ? "emerald" : "amber"}
                      />
                    )}
                  </div>
                </div>

                <AnswerPanel
                  answer={result.answer}
                  knownIds={knownIds}
                  highlightedId={highlightedId}
                  onSelect={select}
                />
                <p className="mt-4 border-t border-slate-800 pt-3 text-[11px] text-slate-500">
                  Suggested actions are advisory and require human review. Cited ids in
                  <span className="mx-1 rounded bg-sky-500/15 px-1 font-mono text-sky-300">blue</span>
                  were returned by the graph; a
                  <span className="mx-1 rounded bg-rose-500/15 px-1 font-mono text-rose-300">red</span>
                  citation means the graph did not support it.
                </p>
              </section>

              {/* Graph */}
              <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
                <h2 className="mb-3 text-sm font-semibold text-slate-200">
                  Dependency graph
                  {highlightedId && (
                    <button
                      type="button"
                      onClick={() => setHighlightedId(null)}
                      className="ml-3 text-xs font-normal text-sky-400 hover:text-sky-300"
                    >
                      clear focus
                    </button>
                  )}
                </h2>
                <GraphCanvas
                  nodes={graphData.nodes}
                  edges={graphData.edges}
                  paths={graphPaths}
                  highlightedId={highlightedId}
                  onSelect={select}
                />
              </section>

              {/* Evidence */}
              <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
                <h2 className="mb-3 text-sm font-semibold text-slate-200">Evidence</h2>
                <EvidencePanel
                  evidence={result.evidence}
                  incidents={result.incidents}
                  decisions={result.decisions}
                  documents={result.documents}
                  highlightedId={highlightedId}
                  onSelect={select}
                />
              </section>
            </div>

            {/* Sidebar */}
            <aside className="space-y-6">
              <Panel title="Impacted services">
                <ImpactList
                  impacted={result.impacted_services}
                  highlightedId={highlightedId}
                  onSelect={select}
                />
              </Panel>

              {result.recommendations.length > 0 && (
                <Panel title="Recommended next steps">
                  <ol className="space-y-2">
                    {result.recommendations.map((rec, i) => (
                      <li key={i} className="text-xs leading-relaxed text-slate-300">
                        <span className="text-slate-500">{i + 1}.</span> {rec.action}
                        <p className="mt-0.5 text-[11px] text-slate-500">{rec.rationale}</p>
                        {rec.suggested_reviewers.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {rec.suggested_reviewers.slice(0, 5).map((person) => (
                              <button
                                key={person.id}
                                type="button"
                                onClick={() => select(person.id)}
                                className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-700"
                              >
                                {person.name}
                              </button>
                            ))}
                          </div>
                        )}
                      </li>
                    ))}
                  </ol>
                </Panel>
              )}

              {result.recalled_investigations.length > 0 && (
                <Panel title="Recalled from memory">
                  <ul className="space-y-2">
                    {result.recalled_investigations.map((item) => (
                      <li key={item.id} className="text-xs leading-relaxed text-slate-400">
                        <p className="text-slate-300">{item.question}</p>
                        <p className="mt-0.5 font-mono text-[10px] text-slate-600">
                          {item.id}
                        </p>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}

              <Panel title="Reasoning trace">
                <StepsTimeline steps={result.steps} />
              </Panel>

              <Panel title="History">
                <HistoryList
                  items={history}
                  activeId={result.investigation_id}
                  loading={historyLoading}
                  onSelect={(q) => {
                    setQuestion(q);
                    void run(q);
                  }}
                />
              </Panel>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Badge({ label, tone }: { label: string; tone: "slate" | "emerald" | "amber" }) {
  const styles = {
    slate: "bg-slate-800 text-slate-400",
    emerald: "bg-emerald-500/15 text-emerald-300",
    amber: "bg-amber-500/15 text-amber-300",
  }[tone];
  return (
    <span className={`rounded px-2 py-0.5 text-[10px] ${styles}`}>{label}</span>
  );
}