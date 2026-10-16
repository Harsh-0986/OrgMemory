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
  EntityListResponse,
  InvestigationAccepted,
  InvestigationStatus,
  FullGraphResponse,
  GraphOverview,
  IngestAccepted,
  IngestCapabilities,
  IngestStatus,
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

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // A FormData body must set its own multipart Content-Type, boundary included;
  // forcing JSON here would make the upload unparseable on the server.
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: Record<string, string> = isForm
    ? { ...((init?.headers as Record<string, string>) ?? {}) }
    : { "Content-Type": "application/json", ...((init?.headers as Record<string, string>) ?? {}) };

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers,
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

  entities: (label: string, q = "") =>
    request<EntityListResponse>(
      `/api/graph/entities?label=${encodeURIComponent(label)}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),

  fullGraph: () => request<FullGraphResponse>("/api/graph/full"),

  neighborhood: (entityId: string, depth = 2) =>
    request<unknown>(
      `/api/graph/neighborhood?entity_id=${encodeURIComponent(entityId)}&depth=${depth}`,
    ),

  /** Starts an investigation and returns immediately (202). */
  startInvestigation: (question: string) =>
    request<InvestigationAccepted>("/api/investigations", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  /** Blocks until the investigation finishes. Used by scripts and tests. */
  investigate: (question: string) =>
    request<InvestigationResponse>("/api/investigations?wait=true", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  investigationStatus: (id: string) =>
    request<InvestigationStatus>(
      `/api/investigations/${encodeURIComponent(id)}/status`,
    ),

  history: (limit = 20) =>
    request<InvestigationHistory>(`/api/investigations/history?limit=${limit}`),

  investigation: (id: string) =>
    request<unknown>(`/api/investigations/${encodeURIComponent(id)}`),

  // -- Ingestion ----------------------------------------------------------

  ingestCapabilities: () => request<IngestCapabilities>("/api/ingest/capabilities"),

  /**
   * Queue a document for ingestion, and return as soon as it is stored.
   *
   * The work behind it is slow: conversion is local, but extraction is a model
   * call that can take minutes. Holding the connection open for that would mean
   * one opaque spinner and a request a proxy may kill first, so the upload is
   * accepted with a job id and `ingestStatus` reports each phase as it finishes.
   */
  startIngestFile: (
    file: File,
    options: { title?: string; sourceType?: string; sourceUri?: string } = {},
  ) => {
    const body = new FormData();
    body.append("file", file);
    if (options.title) body.append("title", options.title);
    body.append("source_type", options.sourceType ?? "upload");
    if (options.sourceUri) body.append("source_uri", options.sourceUri);
    return request<IngestAccepted>("/api/ingest/file", { method: "POST", body });
  },

  /** Queue pasted text. No conversion step, same pipeline afterwards. */
  startIngestText: (
    content: string,
    options: { title?: string; sourceType?: string; sourceUri?: string } = {},
  ) =>
    request<IngestAccepted>("/api/ingest/text", {
      method: "POST",
      body: JSON.stringify({
        content,
        title: options.title ?? "",
        source_type: options.sourceType ?? "note",
        source_uri: options.sourceUri ?? "",
      }),
    }),

  ingestStatus: (jobId: string) =>
    request<IngestStatus>(`/api/ingest/${encodeURIComponent(jobId)}/status`),
};