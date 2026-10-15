"use client";

/**
 * Evidence, as a log of records rather than a stack of cards.
 *
 * Two things get equal visual weight with findings: a recorded cause, and the
 * absence of one. "Cause not recorded" is a real result, and an interface that
 * treats it as empty space teaches the reader to miss it.
 */

import { useState } from "react";
import type { DecisionRow, DocumentRow, Evidence, IncidentRow } from "@/lib/types";

interface EvidencePanelProps {
  evidence: Evidence[];
  incidents: IncidentRow[];
  decisions: DecisionRow[];
  documents: DocumentRow[];
  highlightedId: string | null;
  onSelect: (id: string | null) => void;
}

const TABS = ["Records", "Incidents", "Decisions", "Documents"] as const;
type Tab = (typeof TABS)[number];

export default function EvidencePanel({
  evidence,
  incidents,
  decisions,
  documents,
  highlightedId,
  onSelect,
}: EvidencePanelProps) {
  const [tab, setTab] = useState<Tab>("Records");

  const counts: Record<Tab, number> = {
    Records: evidence.length,
    Incidents: incidents.length,
    Decisions: decisions.length,
    Documents: documents.length,
  };

  return (
    <div>
      <div className="flex gap-6 border-b border-rule">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            className={[
              "-mb-px border-b-[1.5px] pb-2 font-ui text-sm transition",
              tab === name
                ? "border-ink text-ink"
                : "border-transparent text-ink-faint hover:text-ink-soft",
            ].join(" ")}
          >
            {name}
            <span className="ml-1.5 font-mono text-[0.7rem] text-ink-faint">
              {counts[name]}
            </span>
          </button>
        ))}
      </div>

      <div className="pt-4">
        {tab === "Records" && (
          <div className="space-y-4">
            {evidence.length === 0 && <Empty text="No evidence records were retrieved." />}
            {evidence.map((record) => (
              <article key={record.evidence_id} className="border-l border-rule pl-4">
                <p className="font-prose text-[0.95rem] text-ink">{record.summary}</p>

                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <span
                    className={[
                      "font-ui text-[0.7rem]",
                      record.confidence === "confirmed" ? "text-verify" : "text-ink-faint",
                    ].join(" ")}
                  >
                    {record.confidence}
                  </span>
                  {record.tool && (
                    <span className="font-mono text-[0.68rem] text-ink-faint">{record.tool}</span>
                  )}
                  {record.source_ids.slice(0, 10).map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => onSelect(highlightedId === id ? null : id)}
                      className={[
                        "font-mono text-[0.68rem] underline decoration-dotted underline-offset-2 transition",
                        highlightedId === id
                          ? "bg-link text-paper"
                          : "text-link/70 hover:text-link",
                      ].join(" ")}
                    >
                      {id}
                    </button>
                  ))}
                  {record.source_ids.length > 10 && (
                    <span className="font-mono text-[0.68rem] text-ink-faint">
                      +{record.source_ids.length - 10} more
                    </span>
                  )}
                </div>

                {record.caveats.map((caveat) => (
                  <p
                    key={caveat}
                    className="mt-2 bg-signal-wash px-2 py-1 font-ui text-xs text-signal"
                  >
                    {caveat}
                  </p>
                ))}
              </article>
            ))}
          </div>
        )}

        {tab === "Incidents" && (
          <div className="divide-y divide-rule-soft">
            {incidents.length === 0 && (
              <Empty text="No incidents are recorded against these services." />
            )}
            {incidents.map((incident) => (
              <article
                key={`${incident.id}-${incident.service_id}`}
                className="py-4 first:pt-0"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <h4 className="font-ui text-[0.95rem] font-medium text-ink">
                    {incident.title}
                  </h4>
                  <span
                    className={[
                      "font-mono text-[0.7rem]",
                      incident.severity === "sev1" ? "text-signal" : "text-ink-soft",
                    ].join(" ")}
                  >
                    {incident.severity}
                  </span>
                </div>

                <p className="mt-1 font-mono text-[0.68rem] text-ink-faint">
                  {incident.id} · {incident.occurred_at?.slice(0, 10)} · {incident.service_name}
                </p>
                <p className="mt-2 max-w-[70ch] font-prose text-sm leading-relaxed text-ink-soft">
                  {incident.summary}
                </p>

                <p className="mt-2.5 font-ui text-xs">
                  {incident.cause_names.length > 0 ? (
                    <span className="text-ink-faint">
                      Caused by <span className="text-ink">{incident.cause_names.join(", ")}</span>
                    </span>
                  ) : (
                    <span className="bg-signal-wash px-1.5 py-0.5 text-signal">
                      Cause not recorded in the graph
                    </span>
                  )}
                </p>

                {incident.resolver_names.length > 0 && (
                  <p className="mt-1.5 font-ui text-xs text-ink-faint">
                    Resolved by {incident.resolver_names.join(", ")}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}

        {tab === "Decisions" && (
          <ol className="space-y-5">
            {decisions.length === 0 && (
              <Empty text="No architecture decisions are recorded for these services." />
            )}
            {decisions.map((decision) => (
              <li
                key={`${decision.id}-${decision.service_id}`}
                className="border-l border-rule pl-4"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <h4
                    className={[
                      "font-ui text-[0.95rem] font-medium",
                      decision.status === "superseded" ? "text-ink-faint line-through" : "text-ink",
                    ].join(" ")}
                  >
                    {decision.title}
                  </h4>
                  <span className="font-mono text-[0.7rem] text-ink-faint">{decision.date}</span>
                </div>

                <p className="mt-1 font-mono text-[0.68rem] text-ink-faint">
                  {decision.id} · {decision.service_name} · {decision.status}
                </p>
                <p className="mt-2 max-w-[70ch] font-prose text-sm leading-relaxed text-ink-soft">
                  {decision.rationale}
                </p>

                {decision.superseded_by_titles.filter(Boolean).length > 0 && (
                  <p className="mt-2 font-ui text-xs text-verify">
                    Superseded by {decision.superseded_by_titles.filter(Boolean).join(", ")}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}

        {tab === "Documents" && (
          <ul className="space-y-4">
            {documents.length === 0 && (
              <Empty text="No documents are linked to these entities." />
            )}
            {documents.map((doc) => (
              <li key={`${doc.id}-${doc.entity_id}-${doc.relation_type}`} className="border-l border-rule pl-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <h4 className="font-ui text-[0.95rem] font-medium text-ink">{doc.title}</h4>
                  {doc.source_uri && (
                    <a
                      href={doc.source_uri}
                      target="_blank"
                      rel="noreferrer"
                      className="font-ui text-xs text-link underline decoration-dotted underline-offset-2 hover:decoration-link"
                    >
                      Open source
                    </a>
                  )}
                </div>
                <p className="mt-1 font-mono text-[0.68rem] text-ink-faint">
                  {doc.id} · {doc.source_type} · {doc.relation_type.toLowerCase()}{" "}
                  {doc.entity_name}
                </p>
                <p className="mt-2 max-w-[70ch] font-prose text-sm leading-relaxed text-ink-soft">
                  {doc.content}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="font-ui text-sm leading-relaxed text-ink-soft">{text}</p>;
}