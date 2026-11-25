"use client";

import { CircleCheck, CircleX, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import {
  fetchHealth,
  HealthError,
  type HealthReport,
  type ServiceStatus,
  summarize,
} from "@/lib/health";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; report: HealthReport };

export function HealthPanel() {
  const [state, setState] = useState<State>({ kind: "loading" });

  // Bumped by "Check again" to run the effect once more.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then(
      (report) => setState({ kind: "ready", report }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        console.error("Health check failed", error);
        const message =
          error instanceof HealthError
            ? error.message
            : "Something went wrong reading the health check.";
        setState({ kind: "error", message });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  const checkAgain = () => {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  };

  return (
    <section
      aria-labelledby="health-title"
      className="panel"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="health-title" className="display text-[17px]">
          System check
        </h2>
        <button
          type="button"
          onClick={checkAgain}
          disabled={state.kind === "loading"}
          className="btn px-3 py-1.5 text-sm"
        >
          <RefreshCw className="size-4" aria-hidden />
          Check again
        </button>
      </div>

      <div className="mt-4" aria-live="polite">
        {state.kind === "loading" && (
          <p className="flex items-center gap-2 text-muted">
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            Checking Postgres and Meko…
          </p>
        )}
        {state.kind === "error" && (
          <p className="flex items-center gap-2 text-rose">
            <CircleX className="size-4" aria-hidden />
            {state.message}
          </p>
        )}
        {state.kind === "ready" && (
          <>
            <p className="text-2xl font-semibold" data-testid="health-summary">
              {summarize(state.report)}
            </p>
            <ul className="mt-4 space-y-3">
              <ServiceRow name="Postgres" status={state.report.postgres} />
              <ServiceRow name="Meko" status={state.report.meko} />
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

function ServiceRow({ name, status }: { name: string; status: ServiceStatus }) {
  const Icon = status.ok ? CircleCheck : CircleX;
  return (
    <li className="flex items-start gap-3">
      <Icon
        className={`mt-0.5 size-5 shrink-0 ${status.ok ? "text-emerald" : "text-rose"}`}
        aria-label={status.ok ? "ok" : "unreachable"}
      />
      <div>
        <p className="font-medium">{name}</p>
        <p className="text-sm text-muted">
          {status.detail}
          {status.latency_ms !== null && ` · ${status.latency_ms} ms`}
        </p>
      </div>
    </li>
  );
}
