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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiRequestError(
      `Could not reach the OrgMemory API at ${API_BASE_URL}. Is the backend running?`,
      "network_error",
      0,
    );
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