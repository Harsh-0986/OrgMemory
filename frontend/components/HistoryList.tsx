"use client";

/**
 * Past investigations — the visible proof of cross-session memory.
 *
 * Selecting one reuses its question rather than navigating away, because the
 * follow-up is the interesting move: ask something related and watch the agent
 * recall what it already found.
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
    return <p className="font-ui text-xs text-ink-faint">Loading history…</p>;
  }

  if (items.length === 0) {
    return (
      <p className="font-ui text-xs leading-relaxed text-ink-faint">
        Nothing saved yet. Run the primary demo and it will be written to the graph —
        then ask a related follow-up in this session to see it recalled.
      </p>
    );
  }

  return (
    <ol className="space-y-3">
      {items.map((item) => {
        const active = activeId === item.id;
        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.question)}
              disabled={!item.question}
              className={[
                "block w-full border-l-2 pl-3 text-left transition",
                active ? "border-link" : "border-rule-soft hover:border-rule",
              ].join(" ")}
            >
              <p
                className={[
                  "line-clamp-2 font-ui text-xs leading-relaxed",
                  active ? "text-ink" : "text-ink-soft",
                ].join(" ")}
              >
                {item.question}
              </p>
              <p className="mt-1 font-mono text-[0.65rem] text-ink-faint">
                {item.created_at?.slice(0, 16).replace("T", " ") ?? item.id}
                {item.cited_ids.length > 0 && ` · ${item.cited_ids.length} cited`}
              </p>
            </button>
          </li>
        );
      })}
    </ol>
  );
}