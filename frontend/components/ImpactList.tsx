"use client";

/**
 * Impacted services, ordered by hop distance then criticality.
 *
 * The hop count is the whole point of this panel: "directly affected" and
 * "affected through two other systems" are very different statements about
 * risk, and the graph is what separates them.
 */

import type { ImpactedService, NodeRef } from "@/lib/types";

interface ImpactListProps {
  impacted: ImpactedService[];
  highlightedId: string | null;
  onSelect: (id: string | null) => void;
}

const CRITICALITY: Record<string, string> = {
  critical: "bg-rose-500/20 text-rose-300 border-rose-500/40",
  high: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  medium: "bg-sky-500/20 text-sky-300 border-sky-500/40",
  low: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  unproven: "bg-violet-500/20 text-violet-300 border-violet-500/40",
};

export default function ImpactList({ impacted, highlightedId, onSelect }: ImpactListProps) {
  if (impacted.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        The graph records no downstream dependencies for this service.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {impacted.map((item) => {
        const active = highlightedId === item.service.id;
        return (
          <button
            key={item.service.id}
            type="button"
            onClick={() => onSelect(active ? null : item.service.id)}
            className={[
              "w-full rounded-lg border px-3 py-2 text-left transition",
              active
                ? "border-sky-500 bg-sky-500/10"
                : "border-slate-800 bg-slate-900/50 hover:border-slate-700",
            ].join(" ")}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm text-slate-200">{item.service.name}</p>
                <code className="font-mono text-[10px] text-slate-500">{item.service.id}</code>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span
                  className={`rounded border px-1.5 py-0.5 text-[10px] ${
                    CRITICALITY[item.criticality] ?? CRITICALITY.low
                  }`}
                >
                  {item.criticality}
                </span>
                <span
                  className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400"
                  title={`${item.depth} dependency hop(s) from the changed service`}
                >
                  {item.depth} hop{item.depth === 1 ? "" : "s"}
                </span>
              </div>
            </div>
            {item.owners.length > 0 && (
              <p className="mt-1.5 text-xs text-slate-400">
                Owner: {item.owners.map((o: NodeRef) => o.name).join(", ")}
              </p>
            )}
            {item.owners.length === 0 && (
              <p className="mt-1.5 text-xs text-amber-400/80">No owner recorded</p>
            )}
          </button>
        );
      })}
    </div>
  );
}