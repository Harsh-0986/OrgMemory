"use client";

/** Execution trace: which node ran, which tool it called, how long it took. */

import type { ExecutionStep } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-500",
  running: "bg-sky-400 animate-pulse",
  pending: "bg-slate-600",
  skipped: "bg-amber-500",
  failed: "bg-rose-500",
};

export default function StepsTimeline({ steps }: { steps: ExecutionStep[] }) {
  if (steps.length === 0) return null;

  return (
    <ol className="space-y-2">
      {steps.map((step, index) => (
        <li key={`${step.node}-${index}`} className="flex gap-3 text-sm">
          <div className="flex flex-col items-center">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${STATUS_STYLES[step.status] ?? "bg-slate-600"}`} />
            {index < steps.length - 1 && <span className="w-px flex-1 bg-slate-800" />}
          </div>
          <div className="min-w-0 flex-1 pb-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-slate-200">{step.title}</span>
              {step.tool && (
                <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {step.tool}
                </code>
              )}
              {step.duration_ms > 0 && (
                <span className="text-[10px] text-slate-500">{step.duration_ms}ms</span>
              )}
            </div>
            {step.detail && (
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{step.detail}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}