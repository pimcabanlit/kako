// The metrics screen's words. Every figure comes from the backend (api/metrics.py); these only
// name and format what it sends.

import type { MetricsGroup } from "./types.ts";

export const GROUP_WORDS: Record<MetricsGroup, { label: string; note: string }> = {
  household: { label: "Household sessions", note: "the household's own turns" },
  specialists: { label: "Test set, specialists", note: "an orchestrator and four specialists" },
  single: { label: "Test set, one agent", note: "the single-agent baseline" },
};

/** "US$0.0452": costs per turn are small, so four decimals. */
export function usd4(decimal: string): string {
  const value = Number(decimal);
  return Number.isFinite(value) ? `US$${value.toFixed(4)}` : `US$${decimal}`;
}

/** "93.3%" from the backend's percentage; "Not yet" when there is none. */
export function pct(value: string | number | null): string {
  if (value === null) return "Not yet";
  return `${value}%`;
}

/** A meter's fill, 0 to 100, from a percentage. */
export function fill(value: string | number | null): number {
  if (value === null) return 0;
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n));
}

/** 51028 as "51,028", and a decimal string of a whole number the same. */
export function whole(value: string | number): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-US") : String(value);
}

const ALLOWANCES: Record<string, string> = {
  context_search: "Context searches",
  memory_search: "Memory searches",
  knowledgebase_search: "Knowledge-base searches",
  conversation_add_message: "Turns saved",
  conversation_create: "Conversations",
  memory_add: "Memories added",
};

/** A Free-tier allowance in plain words. */
export function allowanceWords(name: string): string {
  return ALLOWANCES[name] ?? name;
}

/** What a run was: replayed from a recording, recorded on Foundry, or live. */
export function modeWords(mode: string | null): string {
  if (mode === "replay") return "replayed from its recording";
  if (mode === "record") return "recorded on Foundry";
  if (mode === "live") return "live on Foundry";
  return mode ?? "";
}

export type OutcomeTone = "emerald" | "rose" | "plain";

/** A Context Gap's outcome after its search was replayed. */
export function outcomeWords(outcome: string | null): { label: string; tone: OutcomeTone } {
  if (outcome === "improved") return { label: "Improved", tone: "emerald" };
  if (outcome === "worse") return { label: "Worse", tone: "rose" };
  if (outcome === "no_change") return { label: "No change", tone: "plain" };
  if (outcome === "no_baseline") return { label: "No score before", tone: "plain" };
  return { label: "Not replayed yet", tone: "plain" };
}

/** How far one score is above another, in points: "+22.1 points", "-3.0 points", "same". */
export function pointsBetween(first: string, second: string): string {
  const diff = Math.round((Number(first) - Number(second)) * 10) / 10;
  if (!Number.isFinite(diff)) return "";
  if (diff === 0) return "same";
  return `${diff > 0 ? "+" : "−"}${Math.abs(diff).toFixed(1)} points`;
}
