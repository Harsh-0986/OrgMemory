"use client";

/**
 * Renders the agent's answer with inline citation chips.
 *
 * The backend writes entity ids inline as `[svc-checkout]`. Those brackets are
 * turned into buttons that focus the matching node in the graph, which is what
 * makes a claim traceable in one click instead of by reading the evidence list.
 *
 * Only a small, deliberate subset of markdown is handled - headings, bullets,
 * bold and inline code. That is all the writer actually emits, and a full
 * markdown parser would be an unnecessary dependency in the render path.
 */

import { Fragment, type ReactNode } from "react";

interface AnswerPanelProps {
  answer: string;
  knownIds: Set<string>;
  highlightedId: string | null;
  onSelect: (id: string | null) => void;
}

const CITATION = /\[([a-z]+-[a-z0-9-]+)\]/gi;

/** Split text into plain runs and citation tokens. */
function tokenize(text: string): Array<{ kind: "text" | "cite"; value: string }> {
  const out: Array<{ kind: "text" | "cite"; value: string }> = [];
  let last = 0;
  CITATION.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION.exec(text)) !== null) {
    if (match.index > last) {
      out.push({ kind: "text", value: text.slice(last, match.index) });
    }
    out.push({ kind: "cite", value: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    out.push({ kind: "text", value: text.slice(last) });
  }
  return out;
}

/** Apply `**bold**` and `` `code` `` inside a plain run. */
function decorate(text: string, key: string, knownIds: Set<string>, onSelect: (id: string | null) => void, highlightedId: string | null): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(
        <strong key={`${key}-b-${match.index}`} className="font-semibold text-slate-100">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      parts.push(
        <code
          key={`${key}-c-${match.index}`}
          className="rounded bg-slate-800/80 px-1 py-0.5 font-mono text-[0.8em] text-sky-300"
        >
          {token.slice(1, -1)}
        </code>,
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderInline(text: string, key: string, knownIds: Set<string>, onSelect: (id: string) => void, highlightedId: string | null): ReactNode[] {
  return tokenize(text).map((token, index) => {
    if (token.kind === "cite") {
      const id = token.value;
      const grounded = knownIds.has(id);
      const isActive = highlightedId === id;
      return (
        <button
          key={`${key}-cite-${index}`}
          type="button"
          onClick={() => onSelect(isActive ? "" : id)}
          title={
            grounded
              ? `Show ${id} in the graph`
              : `${id} is cited but was not returned by the graph`
          }
          className={[
            "mx-0.5 inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[0.72em] transition",
            isActive
              ? "bg-sky-400 text-slate-950"
              : grounded
                ? "bg-sky-500/15 text-sky-300 hover:bg-sky-500/30"
                : "bg-rose-500/15 text-rose-300 hover:bg-rose-500/30",
          ].join(" ")}
        >
          {id}
        </button>
      );
    }
    return <Fragment key={`${key}-t-${index}`}>{decorate(token.value, `${key}-${index}`, knownIds, onSelect, highlightedId)}</Fragment>;
  });
}

export default function AnswerPanel({
  answer,
  knownIds,
  highlightedId,
  onSelect,
}: AnswerPanelProps) {
  if (!answer) {
    return (
      <p className="text-sm text-slate-500">No answer was produced for this question.</p>
    );
  }

  const lines = answer.split("\n");
  const blocks: ReactNode[] = [];

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (line.startsWith("### ")) {
      blocks.push(
        <h4 key={blocks.length} className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
          {line.slice(4)}
        </h4>,
      );
    } else if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={blocks.length} className="mt-6 border-b border-slate-800 pb-1.5 text-sm font-semibold text-slate-200 first:mt-0">
          {line.slice(3)}
        </h3>,
      );
    } else if (/^[-*]\s+/.test(line)) {
      const indent = raw.length - raw.trimStart().length;
      blocks.push(
        <div key={blocks.length} className="flex gap-2 py-0.5" style={{ paddingLeft: `${Math.min(indent, 20)}px` }}>
          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-600" />
          <p className="text-sm leading-relaxed text-slate-300">
            {renderInline(line.replace(/^[-*]\s+/, ""), `li-${blocks.length}`, knownIds, onSelect, highlightedId)}
          </p>
        </div>,
      );
    } else if (/^\d+\.\s+/.test(line)) {
      blocks.push(
        <p key={blocks.length} className="py-0.5 pl-1 text-sm leading-relaxed text-slate-300">
          {renderInline(line, `ol-${blocks.length}`, knownIds, onSelect, highlightedId)}
        </p>,
      );
    } else if (line.trim() === "") {
      blocks.push(<div key={blocks.length} className="h-2" />);
    } else {
      blocks.push(
        <p key={blocks.length} className="py-1 text-sm leading-relaxed text-slate-300">
          {renderInline(line, `p-${blocks.length}`, knownIds, onSelect, highlightedId)}
        </p>,
      );
    }
  }

  return <div>{blocks}</div>;
}