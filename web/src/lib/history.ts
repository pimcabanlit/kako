// How the timeline and decisions screens arrange the household's story. Pure, tested in
// history.test.ts.

import { formatDay } from "./text.ts";
import type { Decision, Thing, TimelineEvent, ValueAt } from "./types.ts";
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

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** "December 2026" from "2026-12-01". */
export function monthWords(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(isoDate);
  const month = match ? MONTHS[Number(match[2]) - 1] : undefined;
  return match && month ? `${month} ${match[1]}` : isoDate;
}

export type Month = { key: string; label: string; events: TimelineEvent[] };

/** The events by month, in the order given (newest first). */
export function byMonth(events: readonly TimelineEvent[]): Month[] {
  const months: Month[] = [];
  for (const event of events) {
    const key = event.on.slice(0, 7);
    const last = months.at(-1);
    if (last && last.key === key) last.events.push(event);
    else months.push({ key, label: monthWords(event.on), events: [event] });
  }
  return months;
}

const EVENT_KIND: Record<string, string> = {
  start: "Starting figures",
  life_event: "Life event",
  correction: "Correction",
  decision: "Decision",
  change: "Facts",
  plan: "Plan",
  session: "Session",
};

/** The short line under an event's headline: when, what kind, and who said yes to it.
 * "Dec 1, 2026 · New job · Approved by Mara". */
export function eventLine(
  event: Pick<TimelineEvent, "kind" | "on" | "detail" | "changes" | "by">,
): string[] {
  const parts = [formatDay(event.on)];
  if (event.kind === "life_event") parts.push(event.detail ?? EVENT_KIND.life_event);
  else if (event.kind === "change")
    parts.push(event.changes.length === 1 ? "1 figure" : `${event.changes.length} figures`);
  else if ((event.kind === "plan" || event.kind === "session") && event.detail)
    parts.push(`${EVENT_KIND[event.kind]}, ${event.detail.toLowerCase()}`);
  else parts.push(EVENT_KIND[event.kind] ?? event.kind);
  if (event.by) parts.push(`${event.kind === "decision" ? "Decided" : "Approved"} by ${event.by}`);
  return parts;
}

const THING_GROUP: Record<string, string> = {
  household: "The household",
  income: "Income",
  expense: "Spending",
  debt: "Debts",
  account: "Savings",
  goal: "Goals",
};

export type ThingGroup = { kind: string; label: string; things: Thing[] };

/** The things by kind, in the order given. */
export function byKind(things: readonly Thing[]): ThingGroup[] {
  const groups: ThingGroup[] = [];
  for (const thing of things) {
    const last = groups.at(-1);
    if (last && last.kind === thing.kind) last.things.push(thing);
    else {
      const label = THING_GROUP[thing.kind] ?? thing.kind;
      groups.push({ kind: thing.kind, label, things: [thing] });
    }
  }
  return groups;
}

export type ThingCard = {
  value: string | null; // what it holds now: its first value ("₱68,000.00")
  words: string; // what that value is ("take-home pay a month"), or that none is kept
  meta: string; // when it last changed, or since when it has held
  coming: string | null; // the day a coming value starts
  corrected: boolean; // a value of it was corrected
};

/** What a thing holds now for one attribute: its current value, else the one coming, else the
 * newest. */
function shownValue(values: readonly ValueAt[]): ValueAt | undefined {
  return (
    values.find((v) => v.state === "current") ??
    values.find((v) => v.state === "coming") ??
    values[0]
  );
}

/** A thing's card: its headline value now (its first attribute: a salary's pay, a debt's
 * balance), when it last changed, and what is coming. The rest waits for its details. */
export function thingCard(thing: Pick<Thing, "attributes">): ThingCard {
  const first = thing.attributes[0];
  const shown = first ? shownValue(first.values) : undefined;
  const values = thing.attributes.flatMap((a) => a.values);
  const coming = values
    .filter((v) => v.state === "coming")
    .map((v) => v.valid_from)
    .sort()[0];
  // A change: a value that took another's place and holds now or held since.
  const changed = thing.attributes
    .flatMap((a) =>
      a.values.filter(
        (v, i) => i < a.values.length - 1 && v.state !== "coming" && v.state !== "corrected",
      ),
    )
    .map((v) => v.valid_from)
    .sort()
    .at(-1);
  const since = values.map((v) => v.valid_from).sort()[0];
  return {
    value: shown?.value ?? null,
    words: first && shown ? first.words : "No values kept for it",
    meta: changed ? `Changed ${formatDay(changed)}` : since ? `Since ${formatDay(since)}` : "",
    coming: coming ?? null,
    corrected: values.some((v) => v.state === "corrected"),
  };
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
