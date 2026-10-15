"use client";

/**
 * Blast radius, ranked by hop distance.
 *
 * Depth is shown as indentation and a left rule rather than as a badge: the
 * list should read as a tree descending from the service you changed, which is
 * exactly what the graph says. A "3 hops" pill restates a number the layout
 * already shows.
 */

import type { ImpactedService } from "@/lib/types";

interface ImpactListProps {
  impacted: ImpactedService[];
  highlightedId: string | null;
  onSelect: (id: string | null) => void;
}

/** Risk tone by criticality. These are the only two accents on the page. */
const TONE: Record<string, string> = {
  critical: "text-signal",
  high: "text-signal/75",
  unproven: "text-verify",
  medium: "text-ink-soft",
  low: "text-ink-faint",
};

export default function ImpactList({ impacted, highlightedId, onSelect }: ImpactListProps) {
  if (impacted.length === 0) {
    return (
      <p className="font-ui text-sm leading-relaxed text-ink-soft">
        The graph records no downstream dependencies for this service.
      </p>
    );
  }

  const maxDepth = Math.max(...impacted.map((i) => i.depth));

  return (
    <ul className="space-y-px">
      {impacted.map((item) => {
        const active = highlightedId === item.service.id;
        // Each hop steps in one level and draws a rule down to its children.
        const indent = 10 + (item.depth - 1) * 18;

        return (
          <li key={item.service.id} style={{ paddingLeft: indent }}>
            <button
              type="button"
              onClick={() => onSelect(active ? null : item.service.id)}
              className={[
                "group -ml-1 flex w-[calc(100%+0.25rem)] items-baseline gap-x-2.5 rounded-[2px] px-1 py-[0.3rem] text-left transition",
                active ? "bg-link-soft" : "hover:bg-paper-raised",
              ].join(" ")}
            >
              <span
                className={`w-px shrink-0 self-stretch ${item.depth > 1 ? "bg-rule" : "bg-transparent"}`}
                aria-hidden
              />
              <span
                className={[
                  "min-w-0 flex-1 truncate font-ui text-sm",
                  active ? "text-link" : "text-ink",
                ].join(" ")}
              >
                {item.service.name}
              </span>
              <span className={`shrink-0 font-mono text-[0.68rem] ${TONE[item.criticality] ?? "text-ink-soft"}`}>
                {item.criticality}
              </span>
            </button>

            {item.owners.length > 0 ? (
              <p
                className="font-ui text-[0.72rem] text-ink-faint"
                style={{ paddingLeft: indent + 14 }}
              >
                {item.owners.map((o) => o.name).join(", ")}
              </p>
            ) : (
              <p
                className="font-ui text-[0.72rem] text-signal/80"
                style={{ paddingLeft: indent + 14 }}
              >
                No owner recorded
              </p>
            )}
          </li>
        );
      })}

      {maxDepth > 1 && (
        <li className="pt-3 font-ui text-[0.72rem] leading-relaxed text-ink-faint">
          Depth is shown by indentation: each level is one dependency hop from the
          service you changed.
        </li>
      )}
    </ul>
  );
}