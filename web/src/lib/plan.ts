// How the plan screen arranges a plan's "why". Pure, tested in plan.test.ts.

import { formatDay } from "./text.ts";
import type { Check, FigureWhy, PlanSummary } from "./types.ts";
import type { Tone } from "./words.ts";
import { listOf, plural } from "./working.ts";

/** A plan's status as the household reads it: the accepted plan is the current one. */
export function planStatus(status: string): { label: string; tone: Tone } {
  if (status === "proposed") return { label: "Proposed", tone: "gold" };
  if (status === "accepted") return { label: "Current", tone: "emerald" };
  if (status === "replaced") return { label: "Replaced", tone: "plain" };
  return { label: status, tone: "plain" };
}

/** "v2 · Dec 1, 2026 · Proposed", for the version picker. */
export function versionLabel(p: PlanSummary): string {
  return `v${p.version} · ${formatDay(p.as_of)} · ${planStatus(p.status).label}`;
}

/** "1 figure and 6 facts": what a figure was built from; null when it read nothing. */
export function builtFrom(figure: Pick<FigureWhy, "inputs" | "facts">): string | null {
  const parts = [
    figure.inputs.length ? plural(figure.inputs.length, "figure") : null,
    figure.facts.length ? plural(figure.facts.length, "fact") : null,
  ].filter((p): p is string => p !== null);
  return parts.length ? listOf(parts) : null;
}

/** Every fact the cited figures rest on, through the figures they were built from, each once
 * and in the order first reached. A figure missing from the map is passed over. */
export function factsBehind(
  figureIds: readonly string[],
  figures: Readonly<Record<string, Pick<FigureWhy, "inputs" | "facts">>>,
): string[] {
  const facts: string[] = [];
  const seenFacts = new Set<string>();
  const seen = new Set<string>();
  const queue = [...figureIds];
  while (queue.length) {
    const id = queue.shift() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    const figure = figures[id];
    if (!figure) continue;
    for (const fact of figure.facts) {
      if (!seenFacts.has(fact)) {
        seenFacts.add(fact);
        facts.push(fact);
      }
    }
    queue.push(...figure.inputs);
  }
  return facts;
}

/** The number check over an option's texts: how many numbers it read, how many matched. */
export function checkTally(checks: readonly Check[]): {
  numbers: number;
  matched: number;
  flagged: number;
} {
  const all = checks.flatMap((c) => c.numbers);
  const matched = all.filter((n) => n.matched !== null).length;
  return { numbers: all.length, matched, flagged: all.length - matched };
}

/** "552 ms", or nothing when the call wasn't timed. */
export function millis(ms: number | null): string | null {
  return ms === null ? null : `${ms.toLocaleString("en-US")} ms`;
}
