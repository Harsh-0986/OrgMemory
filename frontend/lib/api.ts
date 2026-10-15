/**
 * Typed client for the OrgMemory API.
 *
 * The backend returns a structured error envelope for every non-2xx response,
 * so `request` turns that into a thrown `ApiRequestError` with a message safe
 * to show a user. Network failures are normalised the same way rather than
 * leaking a raw TypeError into the UI.
 */

import type {
  ApiError,
  GraphOverview,
  InvestigationHistory,
  InvestigationResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

/** Abort a request that hangs, so the UI can never sit on a spinner forever. */
const REQUEST_TIMEOUT_MS = 90_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (err) {
    // An aborted request is indistinguishable from a hung one to a user, and
    // both deserve a readable message rather than a raw TypeError.
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiRequestError(
        "The request timed out. The backend may be slow or unreachable.",
        "timeout",
        0,
      );
    }
    throw new ApiRequestError(
      `Could not reach the OrgMemory API at ${API_BASE_URL}. Is the backend running, and does its CORS_ORIGINS include this page's origin?`,
      "network_error",
      0,
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as ApiError;
      if (body?.error) {
        code = body.error.code;
        message = body.error.message;
      }
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    throw new ApiRequestError(message, code, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; graph_connected: boolean }>("/health"),

  overview: () => request<GraphOverview>("/api/graph/overview"),

  neighborhood: (entityId: string, depth = 2) =>
    request<unknown>(
      `/api/graph/neighborhood?entity_id=${encodeURIComponent(entityId)}&depth=${depth}`,
    ),

  investigate: (question: string) =>
    request<InvestigationResponse>("/api/investigations", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  history: (limit = 20) =>
    request<InvestigationHistory>(`/api/investigations/history?limit=${limit}`),

  investigation: (id: string) =>
    request<unknown>(`/api/investigations/${encodeURIComponent(id)}`),
};