// The backend's /api/v1, through the web app's rewrite (next.config.ts). Every call throws
// ApiError with a plain message the screen can show as it is.

import type {
  DatapackMetrics,
  Decisions,
  Household,
  Metrics,
  Plan,
  PlanSummary,
  Proposal,
  SessionSummary,
  SessionTurns,
  Timeline,
  TurnAnswer,
} from "./types.ts";

export class ApiError extends Error {
  readonly status: number; // 0: the backend couldn't be reached

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** FastAPI's `detail`: a string, or a list of validation errors. */
export function detailOf(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body))
    return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) =>
        typeof d === "object" && d !== null && "msg" in d
          ? String((d as { msg: unknown }).msg)
          : null,
      )
      .filter((m): m is string => m !== null);
    return messages.length ? messages.join("; ") : null;
  }
  return null;
}

/** What the household reads when a call fails, by status. */
export function messageFor(status: number, detail: string | null): string {
  if (status === 0)
    return "The web app could not reach Kako's backend. Is it running on port 8000?";
  if (status === 503)
    return detail ?? "The backend has no database set (KAKO_DATABASE_URL).";
  if (status === 429)
    return "Kako is still answering another message. Try again when it ends.";
  if (detail) return detail;
  return `The backend answered HTTP ${status}.`;
}

async function call<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, ...rest } = init ?? {};
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      cache: "no-store",
      ...rest,
      headers:
        json === undefined ? rest.headers : { "content-type": "application/json" },
      body: json === undefined ? rest.body : JSON.stringify(json),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, messageFor(0, null));
  }
  if (!response.ok) {
    let detail: string | null = null;
    try {
      detail = detailOf(await response.json());
    } catch {
      detail = null; // not JSON: the status says enough
    }
    throw new ApiError(response.status, messageFor(response.status, detail));
  }
  return (await response.json()) as T;
}

export const api = {
  household: (signal?: AbortSignal) => call<Household>("/household", { signal }),
  sessions: (signal?: AbortSignal) =>
    call<SessionSummary[]>("/sessions", { signal }),
  turns: (sessionId: string, signal?: AbortSignal) =>
    call<SessionTurns>(`/sessions/${encodeURIComponent(sessionId)}/turns`, {
      signal,
    }),
  startSession: (title: string) =>
    call<{ id: string }>("/sessions", { method: "POST", json: { title } }),
  takeTurn: (sessionId: string, message: string, personId: string | null) =>
    call<TurnAnswer>(`/sessions/${encodeURIComponent(sessionId)}/turns`, {
      method: "POST",
      json: personId ? { message, person_id: personId } : { message },
    }),
  endSession: (sessionId: string) =>
    call<{ dream_status: string }>(
      `/sessions/${encodeURIComponent(sessionId)}/end`,
      { method: "POST" },
    ),
  plans: (signal?: AbortSignal) => call<PlanSummary[]>("/plans", { signal }),
  plan: (planId: string, signal?: AbortSignal) =>
    call<Plan>(`/plans/${encodeURIComponent(planId)}`, { signal }),
  timeline: (signal?: AbortSignal) => call<Timeline>("/timeline", { signal }),
  decisions: (signal?: AbortSignal) =>
    call<Decisions>("/decisions", { signal }),
  metrics: (signal?: AbortSignal) => call<Metrics>("/metrics", { signal }),
  mekoMetrics: (signal?: AbortSignal) =>
    call<DatapackMetrics>("/metrics/meko", { signal }),
  proposals: (signal?: AbortSignal) =>
    call<Proposal[]>("/proposals?status=all", { signal }),
  decide: (
    action: "approve" | "reject",
    proposalIds: string[],
    personId: string,
  ) =>
    call<{ id: string; status: string; already: boolean }[]>(
      `/proposals/${action}`,
      {
        method: "POST",
        json: { proposal_ids: proposalIds, person_id: personId },
      },
    ),
};
