/** Worked examples shown on the dashboard. */

/**
 * The primary demo question from the spec, first and highlighted.
 * Every other entry is a known-answer test the backend suite also covers, so
 * the UI never shows a prompt whose answer has not been verified.
 */
export const EXAMPLE_QUESTIONS: Array<{
  label: string;
  question: string;
  hint: string;
  primary?: boolean;
}> = [
  {
    label: "The primary demo",
    primary: true,
    question:
      "Can we replace Payment Service A with Payment Service B? What could break, who should review it, and why do we use the current service?",
    hint: "Requires 3-hop traversal and cross-links people, decisions and incidents.",
  },
  {
    label: "Impact only",
    question: "What depends on the General Ledger Sync?",
    hint: "Pure dependency traversal, one hop outward.",
  },
  {
    label: "Ownership",
    question: "Who owns the Checkout API?",
    hint: "Short-circuits impact analysis and queries ownership directly.",
  },
  {
    label: "Why it was chosen",
    question: "Why do we use Payment Service A?",
    hint: "Retrieves architecture decisions and their rationale.",
  },
  {
    label: "Unknown cause",
    question: "What incidents affected the Webhook Dispatcher and what caused them?",
    hint: "One incident has no recorded cause. The agent must say so.",
  },
  {
    label: "Recall a session",
    question: "Who should review the Payment Service A replacement?",
    hint: "Recalls the earlier investigation from graph memory.",
  },
];