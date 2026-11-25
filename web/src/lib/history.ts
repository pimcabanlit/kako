// How the timeline and decisions screens arrange the household's story. Pure, tested in
// history.test.ts.

import { formatDay } from "./text.ts";
import type { Decision, TimelineEvent, ValueAt } from "./types.ts";
import type { Tone } from "./words.ts";

/** A value's state on the household's date, in words and its colour: what holds now is
 * emerald, what is coming is a change (orange), a corrected mistake is rose. */
export function valueState(state: string): { label: string; tone: Tone } {
  if (state === "current") return { label: "Current", tone: "emerald" };
  if (state === "coming") return { label: "Coming", tone: "orange" };
  if (state === "past") return { label: "Past", tone: "plain" };
  if (state === "corrected") return { label: "Corrected", tone: "rose" };
  return { label: state, tone: "plain" };
}

/** When a value holds: "From Mar 1, 2026", or "Mar 1, 2026 until Dec 1, 2026" once something
 * took its place (the second day is the first one it no longer holds). */
export function windowWords(value: Pick<ValueAt, "valid_from" | "valid_to">): string {
  if (value.valid_to === null) return `From ${formatDay(value.valid_from)}`;
  return `${formatDay(value.valid_from)} until ${formatDay(value.valid_to)}`;
}

export type Day = { on: string; events: TimelineEvent[] };

/** The events by day, in the order given (newest first), with what is ahead of the household's
 * date apart from what has happened. */
export function byDay(events: readonly TimelineEvent[]): { ahead: Day[]; past: Day[] } {
  const ahead: Day[] = [];
  const past: Day[] = [];
  for (const event of events) {
    const days = event.ahead ? ahead : past;
    const last = days.at(-1);
    if (last && last.on === event.on) last.events.push(event);
    else days.push({ on: event.on, events: [event] });
  }
  return { ahead, past };
}

/** Where an event opens: a plan, a session, or the decision on the decisions screen. */
export function eventHref(event: Pick<TimelineEvent, "kind" | "ref">): string | null {
  if (event.ref === null) return null;
  if (event.kind === "plan") return `/plans/${event.ref}`;
  if (event.kind === "session") return `/sessions/${event.ref}`;
  if (event.kind === "decision") return `/decisions#${decisionAnchor(event.ref)}`;
  return null;
}

export function decisionAnchor(id: string): string {
  return `decision-${id}`;
}

/** A decision's standing: one in force, or one the household changed later. */
export function decisionStatus(status: string): { label: string; tone: Tone } {
  if (status === "active") return { label: "In force", tone: "emerald" };
  if (status === "revised") return { label: "Revised", tone: "plain" };
  if (status === "reversed") return { label: "Reversed", tone: "rose" };
  return { label: status, tone: "plain" };
}

/** The household's words when they chose, unless they are the reasoning again. */
export function quoteOf(decision: Pick<Decision, "quote" | "reasoning">): string | null {
  if (!decision.quote) return null;
  const flat = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();
  return flat(decision.quote) === flat(decision.reasoning) ? null : decision.quote;
}

/** "Decided by Mara in Session 2, Sep 15, 2026": who chose, where and when. */
export function decidedLine(
  decision: Pick<Decision, "decided_by" | "session_title" | "on">,
): string {
  const by = decision.decided_by ? `Decided by ${decision.decided_by} in ` : "Decided in ";
  return `${by}${decision.session_title}, ${formatDay(decision.on)}`;
}
