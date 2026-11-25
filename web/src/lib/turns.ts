// A turn whose request ended with no answer may still have been kept. A long turn can outlast the
// connection (a proxy that gives up, a dropped network) while the backend goes on and keeps it, so
// before the screen says a turn failed it reads the session again (docs/architecture.md, "The
// session screen"). Pure: the app shell does the reading.

import type { SessionTurns } from "./types.ts";

/** What the session holds now of a turn sent when it held the turns `before`. */
export type Landed =
  | { kind: "kept"; seed: string }
  | { kind: "running" }
  | { kind: "lost" };

/**
 * Whether a failed request may still have reached the backend: it couldn't be reached at all (0),
 * or something between answered 500 or 504 for it. The backend's own refusals (4xx) and a turn it
 * stopped itself (502, with its reason) mean the turn wasn't kept.
 */
export function mayHaveLanded(status: number): boolean {
  return status === 0 || status === 500 || status === 504;
}

/** The turn with this message that is new since `before`: kept, still running, or not there. */
export function landed(before: readonly string[], now: SessionTurns, message: string): Landed {
  const known = new Set(before);
  const kept = now.turns.find((t) => !known.has(t.seed) && t.message === message);
  if (kept) return { kind: "kept", seed: kept.seed };
  const running = now.running;
  if (running && !known.has(running.seed) && running.message === message) return { kind: "running" };
  return { kind: "lost" };
}
