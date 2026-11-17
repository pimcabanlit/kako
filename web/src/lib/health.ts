// The shape of GET /api/v1/health, as the backend's HealthReport defines it
// (backend/src/kako/health.py). Keep the two in step.

export type ServiceStatus = {
  ok: boolean;
  detail: string;
  latency_ms: number | null;
  version: string | null;
};

export type MekoStatus = ServiceStatus & { target: "local" | "cloud" };

export type HealthReport = {
  status: "ok" | "degraded";
  postgres: ServiceStatus;
  meko: MekoStatus;
};

export class HealthError extends Error {}

/** The one-line summary the page shows, for example "Postgres ok, Meko ok". */
export function summarize(report: HealthReport): string {
  const word = (s: ServiceStatus) => (s.ok ? "ok" : "unreachable");
  return `Postgres ${word(report.postgres)}, Meko ${word(report.meko)}`;
}

/** Ask the backend, through the /api/v1 rewrite. Throws HealthError with a plain message. */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthReport> {
  let response: Response;
  try {
    response = await fetch("/api/v1/health", { cache: "no-store", signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new HealthError("The web app could not reach the backend.");
  }
  if (!response.ok) {
    throw new HealthError(
      `The backend answered HTTP ${response.status}. Is it running on port 8000?`,
    );
  }
  return (await response.json()) as HealthReport;
}
