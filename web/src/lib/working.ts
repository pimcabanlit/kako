// "Show the working": a turn's agents' steps (agent_step rows) arranged the way people read them.
// The orchestrator's steps are the timeline; each specialist's steps sit under the orchestrator's
// ask that they answered. A specialist logs its steps before the ask that called it ends, so a
// specialist step belongs to the first ask of its kind numbered after it. Pure, so it is tested
// on its own (working.test.ts).

import type { Step } from "./types.ts";

export const SPECIALISTS = ["budget", "debt", "savings", "goals"] as const;

export type StepGroup = {
  /** The orchestrator's step; null for a specialist still working (its ask hasn't ended). */
  step: Step | null;
  /** The specialist it asked, for an ask (or for a specialist still working). */
  specialist: string | null;
  /** The specialist's own steps, in their order. */
  children: Step[];
};

function askedOf(step: Step): string | null {
  return step.tool.startsWith("ask_") ? step.tool.slice(4) : null;
}

/** The turn's steps as a timeline of the orchestrator's steps, each ask with its specialist's. */
export function groupSteps(steps: readonly Step[]): StepGroup[] {
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const lead = ordered.filter((s) => !isSpecialist(s.agent));
  const groups: StepGroup[] = lead.map((step) => ({
    step,
    specialist: askedOf(step),
    children: [],
  }));
  const working = new Map<string, StepGroup>();
  for (const step of ordered) {
    if (!isSpecialist(step.agent)) continue;
    const ask = groups.find(
      (g) => g.step !== null && g.specialist === step.agent && g.step.seq > step.seq,
    );
    if (ask) {
      ask.children.push(step);
      continue;
    }
    let open = working.get(step.agent);
    if (!open) {
      open = { step: null, specialist: step.agent, children: [] };
      working.set(step.agent, open);
      groups.push(open);
    }
    open.children.push(step);
  }
  return groups;
}

export function isSpecialist(agent: string): boolean {
  return (SPECIALISTS as readonly string[]).includes(agent);
}

export type StepTone = "ok" | "sent_back" | "refused" | "error";

/** What happened to a step, in the screen's words. A handed-in text that code's checks sent back
 * is the agent's step `error`; a split the reconciliation rules refused is `rejected`. */
export function toneOf(step: Step): StepTone {
  if (step.outcome === "ok") return "ok";
  if (step.outcome === "rejected") return "refused";
  if (step.tool.startsWith("submit_") || step.tool === "propose_change")
    return "sent_back";
  return "error";
}

export const TONE_WORDS: Record<StepTone, string> = {
  ok: "done",
  sent_back: "sent back",
  refused: "refused",
  error: "error",
};

/** A step's tool in plain words. */
export function describeTool(tool: string): string {
  const asked = tool.startsWith("ask_") ? tool.slice(4) : null;
  if (asked) return `Asked the ${asked} specialist`;
  const words: Record<string, string> = {
    run_what_if: "Ran a what-if on the engine",
    get_figures: "Read figures from the engine",
    get_facts: "Read the household's facts",
    get_decisions: "Read past decisions",
    search_memory: "Searched Meko",
    submit_proposal: "Handed in a proposal",
    submit_answer: "Handed in the answer",
    submit_claims: "Handed in what it found",
    propose_change: "Held a change for your yes",
  };
  return words[tool] ?? tool;
}

export type WorkingSummary = {
  steps: number;
  agents: string[]; // the specialists that took part, in the order they first acted
  whatIfs: number;
  sentBack: number;
  refused: number;
  errors: number;
};

export function summarize(steps: readonly Step[]): WorkingSummary {
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const agents: string[] = [];
  for (const s of ordered)
    if (isSpecialist(s.agent) && !agents.includes(s.agent)) agents.push(s.agent);
  const tones = ordered.map(toneOf);
  return {
    steps: ordered.length,
    agents,
    whatIfs: ordered.filter((s) => s.tool === "run_what_if" && s.outcome === "ok")
      .length,
    sentBack: tones.filter((t) => t === "sent_back").length,
    refused: tones.filter((t) => t === "refused").length,
    errors: tones.filter((t) => t === "error").length,
  };
}

/** "13 steps · debt, savings · 4 what-ifs · 1 sent back": the working's one line. */
export function summaryLine(summary: WorkingSummary): string {
  const parts = [plural(summary.steps, "step")];
  if (summary.agents.length)
    parts.push(
      `${listOf(summary.agents)} ${summary.agents.length === 1 ? "specialist" : "specialists"}`,
    );
  if (summary.whatIfs) parts.push(plural(summary.whatIfs, "what-if"));
  if (summary.sentBack) parts.push(`${summary.sentBack} sent back`);
  if (summary.refused) parts.push(`${summary.refused} refused`);
  if (summary.errors) parts.push(plural(summary.errors, "error"));
  return parts.join(" · ");
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function listOf(words: readonly string[]): string {
  if (words.length <= 1) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

/** A step's input, shorter: JSON arguments read better without quotes and braces. */
export function shortInput(input: string, max = 160): string {
  const plain = input.replace(/[{}"[\]]/g, "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max - 1)}…` : plain;
}
