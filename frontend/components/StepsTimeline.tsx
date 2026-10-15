"use client";

/** Reasoning trace: which node ran, which tool it called, what it returned. */

import type { ExecutionStep } from "@/lib/types";

const STATUS: Record<string, { dot: string; label: string }> = {
  completed: { dot: "bg-verify", label: "text-ink-soft" },
  running: { dot: "bg-link animate-pulse", label: "text-ink-soft" },
  pending: { dot: "bg-rule", label: "text-ink-faint" },
  skipped: { dot: "bg-signal/60", label: "text-signal" },
  failed: { dot: "bg-signal", label: "text-signal" },
};

export default function StepsTimeline({ steps }: { steps: ExecutionStep[] }) {
  if (steps.length === 0) return null;

  return (
    <ol className="space-y-0">
      {steps.map((step, index) => {
        const tone = STATUS[step.status] ?? STATUS.pending;
        return (
          <li key={`${step.node}-${index}`} className="relative flex gap-3 pb-3 last:pb-0">
            <div className="flex flex-col items-center pt-[0.45rem]">
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone.dot}`} />
              {index < steps.length - 1 && <span className="w-px flex-1 bg-rule-soft" />}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className={`font-ui text-[0.82rem] ${tone.label}`}>{step.title}</span>
                {step.tool && (
                  <span className="font-mono text-[0.65rem] text-ink-faint">{step.tool}</span>
                )}
                {step.duration_ms > 0 && (
                  <span className="font-mono text-[0.65rem] text-ink-faint">
                    {step.duration_ms}ms
                  </span>
                )}
              </div>
              {step.detail && (
                <p className="mt-0.5 font-ui text-[0.72rem] leading-relaxed text-ink-faint">
                  {step.detail}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}