"use client";

/**
 * "What is loaded" — a browser for the contents of the graph.
 *
 * This exists for the reader who asks *how much does this thing actually know?*
 * Every entity is listed with its full property set, so the dataset's scope and
 * quality can be judged directly rather than inferred from an answer.
 *
 * Same visual language as the dashboard: paper, hairline rules, mono for ids.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApiRequestError } from "@/lib/api";
import type { EntityListResponse, GraphOverview } from "@/lib/types";

/** Which properties are worth showing as columns for each label. */
const COLUMNS: Record<string, string[]> = {
  Service: ["name", "criticality", "tier", "vendor"],
  Person: ["name", "role", "team"],
  Project: ["name", "status", "started"],
  Incident: ["title", "severity", "occurred_at", "root_cause_known"],
  Decision: ["title", "date", "status"],
  Document: ["title", "source_type", "source_uri"],
  Investigation: ["question", "created_at", "status"],
};

const ORDER = [
  "Service",
  "Person",
  "Project",
  "Incident",
  "Decision",
  "Document",
  "Investigation",
];

/** Longest text first would be unreadable; these wrap instead. */
const WIDE = new Set(["description", "content", "summary", "rationale", "question", "title"]);

export default function GraphDataPage() {
  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [label, setLabel] = useState("Service");
  const [search, setSearch] = useState("");
  // The result carries the request it answers. That makes `loading` a derived
  // value - true whenever the stored answer is not for what is currently
  // asked - instead of state that has to be set in sync with the request.
  const [result, setResult] = useState<{
    key: string;
    data: EntityListResponse | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    void api
      .overview()
      .then(setOverview)
      .catch(() => setOverview(null));
  }, []);

  // Typing should not fire a query per keystroke, so the text input and the
  // value that actually drives the request are separate.
  const [debounced, setDebounced] = useState(search);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const requestKey = `${label}\u0000${debounced}`;
  const loading = result?.key !== requestKey;
  const data = result?.data ?? null;
  const error = result?.error ?? null;

  useEffect(() => {
    let cancelled = false;
    // State updates live in the promise callbacks, never synchronously in the
    // effect body, so switching labels does not cascade renders.
    void api
      .entities(label, debounced)
      .then((payload) => {
        if (cancelled) return;
        setResult({ key: requestKey, data: payload, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult({
          key: requestKey,
          data: null,
          error:
            err instanceof ApiRequestError
              ? err.message
              : "Could not load entities.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [label, debounced, requestKey]);

  const columns = COLUMNS[label] ?? ["name"];

  const shown = useMemo(() => {
    const rows = data?.entities ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      JSON.stringify(row.properties).toLowerCase().includes(needle),
    );
  }, [data, search]);

  return (
    <div className="min-h-screen bg-page text-ink">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-[1400px] items-baseline justify-between gap-6 px-6 py-4">
          <div className="flex items-baseline gap-3">
            <Link href="/" className="font-ui text-[1.05rem] font-semibold tracking-tight">
              OrgMemory
            </Link>
            <span className="font-prose text-sm italic text-ink-faint">what is loaded</span>
          </div>
          {overview && (
            <span className="font-mono text-[0.7rem] text-ink-faint">
              {overview.total_nodes} nodes · {overview.total_relationships} edges
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 pb-20">
        <section className="py-8">
          <h1 className="max-w-[28ch] font-prose text-3xl leading-tight">
            Everything the graph holds about this organisation.
          </h1>
          <p className="mt-5 max-w-[62ch] font-prose text-[0.98rem] leading-relaxed text-ink">
            {overview
              ? `${overview.total_nodes} nodes, ${overview.total_relationships} edges, all invented.`
              : "All of it is synthetic."}
          </p>
          <p className="mt-3 max-w-[62ch] font-prose text-[0.98rem] leading-relaxed text-ink-soft">
            Pick a type to read what is stored. Two things are worth looking for: the
            Incident list has one entry with no cause recorded, and Service shows Payment
            Service A depending on Identity while Payment Service B does not. Nothing in
            the data explains either gap — which is what the assistant has to tell you
            when it hits them.
          </p>
        </section>

        {/* Label picker — counts from the overview, so the shape is visible first. */}
        <nav className="flex flex-wrap gap-x-6 gap-y-2 border-b border-rule pb-4">
          {ORDER.map((name) => {
            const count = overview?.node_counts?.[name];
            const active = name === label;
            return (
              <button
                key={name}
                type="button"
                onClick={() => setLabel(name)}
                className={[
                  "font-ui text-sm transition",
                  active
                    ? "text-ink underline decoration-solid underline-offset-4"
                    : "text-ink-faint hover:text-ink",
                ].join(" ")}
              >
                {name}
                {count !== undefined && (
                  <span className="ml-1.5 font-mono text-[0.7rem] text-ink-faint">{count}</span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="flex flex-wrap items-baseline justify-between gap-4 py-5">
          <p className="font-ui text-sm text-ink-soft">
            {loading ? "Loading…" : `${shown.length} ${label} entities`}
          </p>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter these entities…"
            aria-label="Filter entities"
            className="w-full max-w-xs border border-rule bg-page-raised px-3 py-1.5 font-ui text-sm outline-none transition placeholder:text-ink-faint focus:border-link"
          />
        </div>

        {error && (
          <div className="border-l-2 border-signal bg-signal-wash px-4 py-3 font-ui text-sm text-signal">
            {error}
          </div>
        )}

        {!error && (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-rule">
                  <th className="py-2 pr-4 font-ui text-[0.72rem] font-semibold text-ink-faint">
                    id
                  </th>
                  {columns.map((col) => (
                    <th
                      key={col}
                      className="py-2 pr-4 font-ui text-[0.72rem] font-semibold text-ink-faint"
                    >
                      {col.replace(/_/g, " ")}
                    </th>
                  ))}
                  <th className="py-2 font-ui text-[0.72rem] font-semibold text-ink-faint">
                    all properties
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const known = columns.filter((c) => row.properties[c] !== undefined);
                  const rest = Object.entries(row.properties).filter(
                    ([k]) => !columns.includes(k) && k !== "id",
                  );
                  return (
                    <tr key={row.id} className="border-b border-rule-soft align-top">
                      <td className="py-2.5 pr-4 font-mono text-[0.72rem] text-link">
                        {row.id}
                      </td>
                      {columns.map((col) => (
                        <td
                          key={col}
                          className={`py-2.5 pr-4 font-ui text-[0.82rem] ${
                            WIDE.has(col) ? "max-w-[28ch] text-ink-soft" : "text-ink"
                          }`}
                        >
                          {row.properties[col] === undefined
                            ? "—"
                            : String(row.properties[col])}
                        </td>
                      ))}
                      <td className="py-2.5 font-mono text-[0.68rem] text-ink-faint">
                        {known.length === columns.length && rest.length === 0
                          ? "all shown"
                          : rest.map(([k, v]) => (
                              <span key={k} className="mr-3 inline-block">
                                {k}={String(v).slice(0, 40)}
                                {String(v).length > 40 ? "…" : ""}
                              </span>
                            ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {!loading && shown.length === 0 && (
              <p className="py-10 font-ui text-sm text-ink-faint">
                No {label.toLowerCase()} entities match that filter.
              </p>
            )}
          </div>
        )}

        {/* Relationship inventory, straight from the overview. */}
        {overview && (
          <section className="mt-14 border-t border-rule pt-8">
            <h2 className="font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
              Relationships in the graph
            </h2>
            <div className="mt-4 flex flex-wrap gap-x-8 gap-y-2">
              {Object.entries(overview.relationship_counts)
                .sort((a, b) => b[1] - a[1])
                .map(([rel, count]) => (
                  <span key={rel} className="font-mono text-[0.75rem]">
                    <span className="text-ink">{count}</span>{" "}
                    <span className="text-ink-faint">{rel.replace(/_/g, " ")}</span>
                  </span>
                ))}
            </div>
            <p className="mt-4 max-w-[62ch] font-prose text-sm leading-relaxed text-ink-soft">
              <code className="font-mono text-[0.85em]">CITED</code> counts grow with use:
              every investigation writes its citations back as edges, so that is the
              cross-session memory rather than a log file.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}