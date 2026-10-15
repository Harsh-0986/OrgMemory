"use client";

/**
 * Evidence records, incidents, decisions and documents.
 *
 * Caveats are given equal visual weight to findings. A tool that reports
 * "no cause recorded" is as important to surface as one that reports a
 * dependency, and burying it would defeat the point of the product.
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

const TABS = ["Evidence", "Incidents", "Decisions", "Documents"] as const;
type Tab = (typeof TABS)[number];

const CONFIDENCE: Record<string, string> = {
  confirmed: "bg-emerald-500/15 text-emerald-300",
  inferred: "bg-amber-500/15 text-amber-300",
  unknown: "bg-slate-600/30 text-slate-400",
};

export default function EvidencePanel({
  evidence,
  incidents,
  decisions,
  documents,
  highlightedId,
  onSelect,
}: EvidencePanelProps) {
  const [tab, setTab] = useState<Tab>("Evidence");

  const counts: Record<Tab, number> = {
    Evidence: evidence.length,
    Incidents: incidents.length,
    Decisions: decisions.length,
    Documents: documents.length,
  };

  return (
    <div>
      <div className="flex flex-wrap gap-1 border-b border-slate-800">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            className={[
              "-mb-px border-b-2 px-3 py-2 text-xs transition",
              tab === name
                ? "border-sky-400 text-slate-100"
                : "border-transparent text-slate-500 hover:text-slate-300",
            ].join(" ")}
          >
            {name}
            <span className="ml-1.5 text-slate-600">{counts[name]}</span>
          </button>
        ))}
      </div>

      <div className="pt-3">
        {tab === "Evidence" &&
          (evidence.length === 0 ? (
            <Empty text="No evidence records were retrieved." />
          ) : (
            <ul className="space-y-2">
              {evidence.map((record) => (
                <li key={record.evidence_id} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm leading-relaxed text-slate-300">{record.summary}</p>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                        CONFIDENCE[record.confidence] ?? CONFIDENCE.unknown
                      }`}
                    >
                      {record.confidence}
                    </span>
                  </div>

                  {record.source_ids.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {record.source_ids.slice(0, 12).map((id) => {
                        const active = highlightedId === id;
                        return (
                          <button
                            key={id}
                            type="button"
                            onClick={() => onSelect(active ? null : id)}
                            className={[
                              "rounded px-1.5 py-0.5 font-mono text-[10px] transition",
                              active
                                ? "bg-sky-400 text-slate-950"
                                : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200",
                            ].join(" ")}
                          >
                            {id}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {record.caveats.map((caveat) => (
                    <p
                      key={caveat}
                      className="mt-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200"
                    >
                      {caveat}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          ))}

        {tab === "Incidents" &&
          (incidents.length === 0 ? (
            <Empty text="No incidents are recorded against these services." />
          ) : (
            <ul className="space-y-2">
              {incidents.map((incident) => (
                <li key={`${incident.id}-${incident.service_id}`} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-slate-200">{incident.title}</p>
                    <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
                      {incident.severity}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-slate-500">
                    {incident.id} · {incident.occurred_at?.slice(0, 10)} · affected{" "}
                    {incident.service_name}
                  </p>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{incident.summary}</p>

                  <p className="mt-2 text-xs">
                    {incident.cause_names.length > 0 ? (
                      <span className="text-slate-400">
                        Caused by{" "}
                        {incident.cause_names.map((name, i) => (
                          <span key={name}>
                            {i > 0 && ", "}
                            <span className="text-slate-200">{name}</span>
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-slate-300">
                        Cause not recorded in the graph
                      </span>
                    )}
                  </p>

                  {incident.resolver_names.length > 0 && (
                    <p className="mt-1.5 text-xs text-slate-500">
                      Resolved by {incident.resolver_names.join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ))}

        {tab === "Decisions" &&
          (decisions.length === 0 ? (
            <Empty text="No architecture decisions are recorded for these services." />
          ) : (
            <ul className="space-y-2">
              {decisions.map((decision) => (
                <li key={`${decision.id}-${decision.service_id}`} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-slate-200">{decision.title}</p>
                    <span
                      className={[
                        "shrink-0 rounded px-1.5 py-0.5 text-[10px]",
                        decision.status === "accepted"
                          ? "bg-emerald-500/15 text-emerald-300"
                          : decision.status === "superseded"
                            ? "bg-slate-600/30 text-slate-400 line-through"
                            : "bg-amber-500/15 text-amber-300",
                      ].join(" ")}
                    >
                      {decision.status}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-slate-500">
                    {decision.id} · {decision.date} · {decision.service_name}
                  </p>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{decision.rationale}</p>
                  {decision.superseded_by_titles.filter(Boolean).length > 0 && (
                    <p className="mt-2 rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-xs text-violet-200">
                      Superseded by {decision.superseded_by_titles.filter(Boolean).join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ))}

        {tab === "Documents" &&
          (documents.length === 0 ? (
            <Empty text="No documents are linked to these entities." />
          ) : (
            <ul className="space-y-2">
              {documents.map((doc) => (
                <li key={`${doc.id}-${doc.entity_id}-${doc.relation_type}`} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <p className="text-sm text-slate-200">{doc.title}</p>
                  <p className="mt-1 font-mono text-[10px] text-slate-500">
                    {doc.id} · {doc.source_type} · {doc.relation_type.toLowerCase()}{" "}
                    {doc.entity_name}
                  </p>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{doc.content}</p>
                  {doc.source_uri && (
                    <a
                      href={doc.source_uri}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-block text-xs text-sky-400 hover:text-sky-300"
                    >
                      Open source ↗
                    </a>
                  )}
                </li>
              ))}
            </ul>
          ))}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-4 text-sm text-slate-500">{text}</p>;
}