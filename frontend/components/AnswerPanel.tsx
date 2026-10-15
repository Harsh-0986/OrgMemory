"use client";

/**
 * The answer, set as a document rather than a chat bubble.
 *
 * Long-form prose deserves a serif and a real measure, so the answer is the one
 * block on the page that reads as writing. Citations are the connective tissue
 * between the prose and the graph, so they render as ink-blue underlined
 * monospace identifiers - clickable, and unmistakably references rather than
 * emphasis.
 *
 * The `##` sections the writer emits become ruled headings; `###` subheads are
 * content, not labels, so they stay in sentence case.
 */

import { Fragment, type ReactNode } from "react";

interface AnswerPanelProps {
  answer: string;
  knownIds: Set<string>;
  highlightedId: string | null;
  onSelect: (id: string | null) => void;
}

const CITATION = /\[([a-z]+-[a-z0-9-]+)\]/gi;

/** Split a run into plain text and citation tokens. */
function tokenize(text: string): Array<{ kind: "text" | "cite"; value: string }> {
  const out: Array<{ kind: "text" | "cite"; value: string }> = [];
  let last = 0;
  CITATION.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION.exec(text)) !== null) {
    if (match.index > last) out.push({ kind: "text", value: text.slice(last, match.index) });
    out.push({ kind: "cite", value: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
  return out;
}

/** `**bold**` and `` `code` `` inside a plain run. */
function decorate(text: string, key: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(
        <strong key={`${key}-b-${match.index}`} className="font-semibold text-ink">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      parts.push(
        <code
          key={`${key}-c-${match.index}`}
          className="rounded-[2px] bg-plate/10 px-1 py-px font-mono text-[0.82em] text-ink-soft"
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

function renderInline(
  text: string,
  key: string,
  knownIds: Set<string>,
  onSelect: (id: string) => void,
  highlightedId: string | null,
): ReactNode[] {
  return tokenize(text).map((token, index) => {
    if (token.kind === "text") {
      return <Fragment key={`${key}-t-${index}`}>{decorate(token.value, `${key}-${index}`)}</Fragment>;
    }

    const id = token.value;
    const grounded = knownIds.has(id);
    const isActive = highlightedId === id;

    return (
      <button
        key={`${key}-c-${index}`}
        type="button"
        onClick={() => onSelect(isActive ? "" : id)}
        title={grounded ? `Show ${id} in the graph` : `${id} was not returned by the graph`}
        className={[
          "mx-px font-mono text-[0.82em] underline decoration-dotted underline-offset-2 transition",
          isActive
            ? "bg-link text-paper decoration-solid"
            : grounded
              ? "text-link decoration-link/40 hover:decoration-link"
              : "text-signal decoration-signal/40 hover:decoration-signal",
        ].join(" ")}
      >
        {id}
      </button>
    );
  });
}

export default function AnswerPanel({
  answer,
  knownIds,
  highlightedId,
  onSelect,
}: AnswerPanelProps) {
  if (!answer) {
    return <p className="font-prose text-ink-soft">No answer was produced for this question.</p>;
  }

  const blocks: ReactNode[] = [];

  for (const raw of answer.split("\n")) {
    const line = raw.trimEnd();

    if (line.startsWith("### ")) {
      blocks.push(
        <h4 key={blocks.length} className="mt-6 font-ui text-[0.95rem] font-semibold text-ink">
          {line.slice(4)}
        </h4>,
      );
    } else if (line.startsWith("## ")) {
      blocks.push(
        <h3
          key={blocks.length}
          className="mt-10 border-b border-rule pb-1.5 font-ui text-[0.8rem] font-semibold tracking-wide text-ink-soft first:mt-0"
        >
          {line.slice(3)}
        </h3>,
      );
    } else if (/^\s*[-*]\s+/.test(line)) {
      const indent = raw.length - raw.trimStart().length;
      blocks.push(
        <div
          key={blocks.length}
          className="flex gap-3"
          style={{ paddingLeft: `${Math.min(indent * 0.6 + 6, 28)}px` }}
        >
          <span className="mt-[0.62rem] h-px w-3 shrink-0 bg-rule" />
          <p className="font-prose text-[0.95rem] text-ink">
            {renderInline(line.replace(/^\s*[-*]\s+/, ""), `li-${blocks.length}`, knownIds, onSelect, highlightedId)}
          </p>
        </div>,
      );
    } else if (/^\s*\d+\.\s+/.test(line)) {
      const indent = raw.length - raw.trimStart().length;
      blocks.push(
        <p
          key={blocks.length}
          className="font-prose text-[0.95rem] text-ink"
          style={{ paddingLeft: `${Math.min(indent * 0.6, 28)}px` }}
        >
          {renderInline(line, `ol-${blocks.length}`, knownIds, onSelect, highlightedId)}
        </p>,
      );
    } else if (line.trim() === "") {
      blocks.push(<div key={blocks.length} className="h-2" />);
    } else {
      blocks.push(
        <p key={blocks.length} className="font-prose text-[0.95rem] text-ink">
          {renderInline(line, `p-${blocks.length}`, knownIds, onSelect, highlightedId)}
        </p>,
      );
    }
  }

  return <div className="animate-rise">{blocks}</div>;
}