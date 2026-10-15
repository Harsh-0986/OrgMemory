"use client";

/**
 * Past investigations.
 *
 * This is the visible proof of cross-session memory: an investigation run now
 * should appear in the sidebar of the next one, and selecting an entry here
 * reuses its question.
 */

import type { InvestigationSummary } from "@/lib/types";

interface HistoryListProps {
  items: InvestigationSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (question: string) => void;
}

export default function HistoryList({ items, activeId, loading, onSelect }: HistoryListProps) {
  if (loading) {
    return <p className="text-xs text-slate-500">Loading history…</p>;
  }

  if (items.length === 0) {
    return (
      <p className="text-xs leading-relaxed text-slate-500">
        No investigations yet. Run the primary demo and it will be saved to the graph —
        then ask a follow-up question in this same session to see it recalled.
      </p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            onClick={() => onSelect(item.question)}
            disabled={!item.question}
            className={[
              "w-full rounded-lg border px-2.5 py-2 text-left transition disabled:cursor-default",
              activeId === item.id
                ? "border-sky-600 bg-sky-500/10"
                : "border-slate-800 bg-slate-900/40 hover:border-slate-700",
            ].join(" ")}
          >
            <p className="line-clamp-2 text-xs leading-relaxed text-slate-300">{item.question}</p>
            <p className="mt-1 font-mono text-[10px] text-slate-500">
              {item.created_at?.slice(0, 16).replace("T", " ") ?? item.id}
              {item.cited_ids.length > 0 && ` · ${item.cited_ids.length} cited`}
            </p>
          </button>
        </li>
      ))}
    </ul>
  );
}