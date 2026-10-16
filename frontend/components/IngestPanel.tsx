"use client";

/**
 * "Add data" — the one place the graph grows from outside the seed dataset.
 *
 * Drop in a file or paste text, and it becomes Markdown, then entities. The
 * report underneath is the point of the panel: it says separately what was
 * learned and what was already known, and it shows every proposal that was
 * refused with the reason. A tool that silently invents entities is worse than
 * one that says "I could not read this", so the failures are as prominent as the
 * successes.
 *
 * The upload is *queued*, not held open. Extraction is a model call that can
 * take minutes, so the POST returns as soon as the document is stored and the
 * panel polls for progress: each phase appears as it finishes. That is the
 * difference between a two-minute wait and a two-minute spinner.
 */

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiRequestError } from "@/lib/api";
import type { IngestCapabilities, IngestReport, IngestStep } from "@/lib/types";

type Mode = "file" | "paste";

const POLL_MS = 1200;

/**
 * Deliberately generous, matching the dashboard's investigations. The backend
 * gives each model call a 60s timeout with two retries, so a slow-but-working
 * upload can legitimately take minutes; a tighter deadline here would abandon
 * jobs that were going to finish.
 */
const DEADLINE_MS = 900_000;

function humanSize(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/** "41ms" under a second, "18.4s" above it. "0.0s" tells the reader nothing. */
function duration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default function IngestPanel({ onIngested }: { onIngested?: () => void }) {
  const [caps, setCaps] = useState<IngestCapabilities | null>(null);

  const [mode, setMode] = useState<Mode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [dragging, setDragging] = useState(false);

  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState("");
  const [steps, setSteps] = useState<IngestStep[]>([]);
  const [report, setReport] = useState<IngestReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Identifies the current upload, so a poll loop from a superseded or
  // unmounted panel cannot write its result over a newer one.
  const activeRun = useRef<symbol | null>(null);

  // Asked once: the panel needs to know the accepted extensions and whether a
  // model is configured before it offers the control, not after a failed upload.
  useEffect(() => {
    let cancelled = false;
    void api
      .ingestCapabilities()
      .then((payload) => {
        if (!cancelled) setCaps(payload);
      })
      .catch(() => {
        if (!cancelled) setCaps(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Abandon any in-flight poll loop when the panel goes away.
  useEffect(
    () => () => {
      activeRun.current = null;
    },
    [],
  );

  const accepted = caps?.supported_extensions.join(",") ?? "";
  const tooBig = Boolean(caps && file && file.size > caps.max_upload_bytes);
  const ready =
    mode === "file" ? Boolean(file) && !tooBig : text.trim().length > 0;

  function choose(next: File | null) {
    setFile(next);
    setError(null);
  }

  async function submit() {
    if (!ready || busy) return;

    const token = Symbol("ingest");
    activeRun.current = token;

    setBusy(true);
    setError(null);
    setReport(null);
    setSteps([]);
    setWorking("");

    const options = {
      title: title.trim(),
      sourceType: sourceType || (mode === "file" ? "upload" : "note"),
    };

    try {
      const queued =
        mode === "file" && file
          ? await api.startIngestFile(file, options)
          : await api.startIngestText(text, options);

      if (activeRun.current !== token) return;

      // The document is stored by now, so the fields have done their job.
      // Re-submitting the same content would just queue a second copy.
      setWorking(queued.title);
      setText("");
      setFile(null);
      setTitle("");

      for (let waited = 0; waited < DEADLINE_MS; waited += POLL_MS) {
        if (activeRun.current !== token) return;

        await new Promise((resolve) => setTimeout(resolve, POLL_MS));

        const status = await api.ingestStatus(queued.job_id);
        setSteps(status.steps);

        if (!status.done) continue;

        if (status.status !== "completed" || !status.result) {
          setError(status.error ?? "The document could not be ingested.");
          return;
        }

        setReport(status.result);
        onIngested?.();
        return;
      }

      setError("The upload is taking longer than expected. Check the backend logs.");
    } catch (err) {
      if (activeRun.current !== token) return;
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "The document could not be ingested.",
      );
    } finally {
      if (activeRun.current === token) {
        activeRun.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <section className="mt-8 border border-rule bg-page-raised">
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-rule px-5 py-3">
        <h2 className="font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft">
          Add data
        </h2>
        <div className="flex gap-4">
          {(["file", "paste"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                setError(null);
              }}
              className={[
                "font-ui text-[0.78rem] transition",
                mode === m
                  ? "text-ink underline decoration-solid underline-offset-4"
                  : "text-ink-faint hover:text-ink-soft",
              ].join(" ")}
            >
              {m === "file" ? "Upload a file" : "Paste text"}
            </button>
          ))}
        </div>
      </div>

      <div className="px-5 py-5">
        {caps && !caps.model_available && (
          <p className="mb-4 border-l-2 border-link bg-link-soft px-3 py-2 font-ui text-[0.78rem] leading-relaxed text-ink-soft">
            No model is configured, so the document will be stored and searchable,
            but no entities will be extracted from it. Set{" "}
            <code className="font-mono text-[0.9em]">NVIDIA_API_KEY</code> or{" "}
            <code className="font-mono text-[0.9em]">GOOGLE_API_KEY</code> to have
            it read the document.
          </p>
        )}

        <div className="grid gap-5 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          {mode === "file" ? (
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const dropped = e.dataTransfer.files?.[0];
                if (dropped) choose(dropped);
              }}
              className={[
                "flex cursor-pointer flex-col items-center justify-center gap-1 border border-dashed px-4 py-8 text-center transition",
                dragging ? "border-link bg-link-soft" : "border-rule hover:border-ink-faint",
              ].join(" ")}
            >
              <span className="font-ui text-sm text-ink">
                {file ? file.name : "Drop a document here, or choose one"}
              </span>
              <span className="font-mono text-[0.68rem] text-ink-faint">
                {file
                  ? `${humanSize(file.size)}${caps ? ` · limit ${humanSize(caps.max_upload_bytes)}` : ""}`
                  : accepted
                    ? accepted.split(",").slice(0, 8).join(" ")
                    : "pdf, docx, pptx, xlsx, md, html, txt"}
              </span>
              <input
                type="file"
                accept={accepted || undefined}
                className="sr-only"
                onChange={(e) => choose(e.target.files?.[0] ?? null)}
              />
            </label>
          ) : (
            <textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setError(null);
              }}
              rows={7}
              placeholder="Paste a runbook, an ADR, a postmortem, meeting notes…"
              aria-label="Document text"
              className="border border-rule bg-page px-3 py-2 font-prose text-[0.9rem] leading-relaxed outline-none transition placeholder:text-ink-faint focus:border-link"
            />
          )}

          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="font-ui text-[0.7rem] font-semibold text-ink-faint">
                title (optional)
              </span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Taken from the filename"
                className="border border-rule bg-page px-3 py-1.5 font-ui text-sm outline-none transition placeholder:text-ink-faint focus:border-link"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="font-ui text-[0.7rem] font-semibold text-ink-faint">
                kind
              </span>
              <select
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value)}
                className="border border-rule bg-page px-3 py-1.5 font-ui text-sm outline-none transition focus:border-link"
              >
                <option value="">
                  {mode === "file" ? "upload" : "note"} (default)
                </option>
                {(caps?.source_types ?? []).map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              onClick={() => void submit()}
              disabled={!ready || busy}
              className="mt-auto border border-ink bg-ink px-4 py-2 font-ui text-sm text-page transition disabled:cursor-not-allowed disabled:border-rule disabled:bg-transparent disabled:text-ink-faint"
            >
              {busy ? "Working…" : "Add to the graph"}
            </button>
          </div>
        </div>

        {tooBig && caps && (
          <p className="mt-3 font-ui text-[0.78rem] text-signal">
            That file is larger than the {humanSize(caps.max_upload_bytes)} limit.
          </p>
        )}

        {busy && <Progress title={working} steps={steps} />}

        {error && (
          <div className="mt-4 border-l-2 border-signal bg-signal-wash px-4 py-3 font-ui text-sm text-signal">
            {error}
          </div>
        )}

        {report && <Report report={report} steps={steps} />}
      </div>
    </section>
  );
}

/**
 * What the upload is doing, as it does it.
 *
 * The wait is real - extraction is a model call - so the honest thing is to show
 * which phase is running rather than a spinner that says nothing. A failed
 * conversion never reaches the read step, and the missing line is the diagnosis.
 */
function Progress({ title, steps }: { title: string; steps: IngestStep[] }) {
  return (
    <div className="mt-5 border-t border-rule pt-4" aria-live="polite">
      <p className="font-ui text-[0.8rem] text-ink">
        {title ? (
          <>
            Reading <span className="italic">{title}</span>
          </>
        ) : (
          "Storing the document…"
        )}
      </p>

      <ol className="mt-3 flex flex-col gap-2">
        {steps.map((step) => (
          <li key={step.phase} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="w-16 shrink-0 font-mono text-[0.66rem] uppercase tracking-wide text-ink-faint">
              {step.phase}
            </span>
            <span className="font-ui text-[0.82rem] text-ink">{step.title}</span>
            {step.detail && (
              <span className="font-prose text-[0.8rem] text-ink-soft">
                {step.detail}
              </span>
            )}
            <span className="font-mono text-[0.66rem] text-ink-faint">
              {duration(step.duration_ms)}
            </span>
          </li>
        ))}
        <li className="flex items-baseline gap-3">
          <span className="w-16 shrink-0 font-mono text-[0.66rem] uppercase tracking-wide text-ink-faint">
            {steps.length === 0 ? "queued" : "reading"}
          </span>
          <span className="font-ui text-[0.82rem] text-ink-faint">
            {steps.length === 0
              ? "Converting to Markdown…"
              : "Still working — a model call is not instant."}
          </span>
        </li>
      </ol>

      <p className="mt-3 max-w-[62ch] font-prose text-[0.8rem] leading-relaxed text-ink-faint">
        Conversion happens locally; reading the document is a model call, which is
        the slow part. Each phase above is reported as it finishes, so a long wait
        still shows progress.
      </p>
    </div>
  );
}

/** What the upload did, told in the order that matters: learned, then linked. */
function Report({ report, steps }: { report: IngestReport; steps: IngestStep[] }) {
  const learned = report.entities_created.length;
  const linked = report.entities_linked.length;

  return (
    <div className="mt-6 border-t border-rule pt-5" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="font-prose text-[0.95rem] leading-relaxed text-ink">
          <span className="font-mono text-[0.8rem] text-link">{report.document_id}</span>{" "}
          stored as <span className="italic">{report.title}</span>
          {report.summary ? ` — ${report.summary}` : ""}
        </p>
        <span className="font-mono text-[0.68rem] text-ink-faint">
          {report.markdown_chars.toLocaleString()} chars
          {report.truncated ? " (trimmed for reading)" : ""}
        </span>
      </div>

      {steps.length > 0 && (
        <p className="mt-2 font-mono text-[0.68rem] text-ink-faint">
          {steps
            .map((step) => `${step.phase} ${duration(step.duration_ms)}`)
            .join(" · ")}
        </p>
      )}

      {!report.model_used && (
        <p className="mt-3 border-l-2 border-link bg-link-soft px-3 py-2 font-ui text-[0.8rem] leading-relaxed text-ink-soft">
          No model was available, so nothing was extracted. The document is stored
          and can be cited by an investigation.
        </p>
      )}

      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <Group
          heading={`New to the graph · ${learned}`}
          count={learned}
          empty="Nothing new — everything it mentioned was already known."
        >
          {report.entities_created.map((entity) => (
            <Chip key={entity.id} id={entity.id} name={entity.name} type={entity.type} />
          ))}
        </Group>

        <Group
          heading={`Already known · ${linked}`}
          count={linked}
          empty={
            report.model_used
              ? "Nothing it mentioned was already in the graph."
              : "—"
          }
        >
          {report.entities_linked.map((entity) => (
            <Chip key={entity.id} id={entity.id} name={entity.name} type={entity.type} />
          ))}
        </Group>
      </div>

      {report.relationships_created.length > 0 && (
        <div className="mt-5">
          <h3 className="font-ui text-[0.7rem] font-semibold tracking-wide text-ink-faint">
            relationships written · {report.relationships_created.length}
          </h3>
          <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
            {report.relationships_created.map((rel) => (
              <li key={rel} className="font-mono text-[0.72rem] text-ink-soft">
                {rel}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.rejected.length > 0 && (
        <div className="mt-5 border-l-2 border-signal pl-3">
          <h3 className="font-ui text-[0.7rem] font-semibold tracking-wide text-signal">
            refused · {report.rejected.length}
          </h3>
          <ul className="mt-2 flex flex-col gap-1">
            {report.rejected.map((item, index) => (
              <li key={`${item.item}-${index}`} className="font-ui text-[0.78rem] text-ink-soft">
                <span className="font-mono text-[0.72rem] text-ink">{item.item}</span>{" "}
                — {item.reason}
              </li>
            ))}
          </ul>
          <p className="mt-2 max-w-[62ch] font-prose text-[0.8rem] leading-relaxed text-ink-faint">
            These were proposed by the reader and rejected before touching the
            graph: a label or relationship type outside the schema, or an
            endpoint that resolves to nothing. Refusals are shown rather than
            swallowed, because a misread document and a broken reader look
            identical otherwise.
          </p>
        </div>
      )}
    </div>
  );
}

function Group({
  heading,
  count,
  empty,
  children,
}: {
  heading: string;
  count: number;
  empty: string;
  children: ReactNode;
}) {
  return (
    <div>
      <h3 className="font-ui text-[0.7rem] font-semibold tracking-wide text-ink-faint">
        {heading}
      </h3>
      {count === 0 ? (
        <p className="mt-2 font-prose text-[0.85rem] leading-relaxed text-ink-faint">
          {empty}
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1.5">{children}</ul>
      )}
    </div>
  );
}

function Chip({ id, name, type }: { id: string; name: string; type: string }) {
  return (
    <li className="flex flex-wrap items-baseline gap-2 border-b border-rule-soft pb-1.5 last:border-0">
      <span className="font-ui text-[0.85rem] text-ink">{name}</span>
      <span className="font-ui text-[0.68rem] uppercase tracking-wide text-ink-faint">
        {type}
      </span>
      <span className="font-mono text-[0.68rem] text-link">{id}</span>
    </li>
  );
}
