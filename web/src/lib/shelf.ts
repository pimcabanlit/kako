// The decisions screen as a bookshelf: each decision a book, opened at one of three bookmarks.
// Pure, tested in shelf.test.ts. Everything here is worked out from GET /api/v1/decisions alone.

import { optionParts } from "./text.ts";
import type { ChangedFact, Decision, DecisionOption, RestsOn } from "./types.ts";
import { plural } from "./working.ts";

// --- The shelf -----------------------------------------------------------------------------------

export type ShelfView = "all" | "revisit" | "in-force" | "revised";

/** Whether a decision sits on the shelf in a view: every one, those to revisit, those in force,
 * or those the household changed later (revised or reversed). */
export function onShelf(decision: Pick<Decision, "status" | "revisit">, view: ShelfView): boolean {
  if (view === "revisit") return decision.revisit.length > 0;
  if (view === "in-force") return decision.status === "active";
  if (view === "revised") return decision.status !== "active";
  return true;
}

export const SHELF_VIEWS: readonly { id: ShelfView; label: string }[] = [
  { id: "all", label: "All" },
  { id: "revisit", label: "To revisit" },
  { id: "in-force", label: "In force" },
  { id: "revised", label: "Revised" },
];

/** The shelf's chips with how many books each shows: "All 3", "To revisit 3". */
export function shelfChips(
  decisions: readonly Pick<Decision, "status" | "revisit">[],
): { id: ShelfView; label: string }[] {
  return SHELF_VIEWS.map((v) => ({
    id: v.id,
    label: `${v.label} ${decisions.filter((d) => onShelf(d, v.id)).length}`,
  }));
}

export const COVERS = 3;

/** Each book's cover, by the session it was made in: the oldest session's books get cover 0, the
 * next session's cover 1, and so on round the covers. Decoration only: it means nothing else. */
export function coverOf(
  decisions: readonly Pick<Decision, "id" | "session_id" | "on">[],
): Map<string, number> {
  const sessions: string[] = [];
  for (const d of [...decisions].sort((a, b) => a.on.localeCompare(b.on))) {
    if (!sessions.includes(d.session_id)) sessions.push(d.session_id);
  }
  return new Map(decisions.map((d) => [d.id, sessions.indexOf(d.session_id) % COVERS]));
}

export type CoverIcon = "trip" | "card" | "buffer" | "school" | "home" | "book";

const ICON_WORDS: readonly [CoverIcon, RegExp][] = [
  ["trip", /\b(trip|travel|holiday|vacation)\b/i],
  ["buffer", /\b(buffer|emergency|rainy)\b/i],
  ["school", /\b(school|tuition)\b/i],
  ["home", /\b(house|home|rent)\b/i],
  ["card", /\b(card|loan|debt)\b/i],
];

/** The picture on a cover, from what was chosen first, then from the question: the trip for "keep
 * it for the trip", the card for "pay down the credit card". A plain book when no word fits. */
export function coverIcon(decision: Pick<Decision, "question" | "chosen">): CoverIcon {
  for (const text of [decision.chosen, decision.question]) {
    const found = ICON_WORDS.find(([, words]) => words.test(text));
    if (found) return found[0];
  }
  return "book";
}

export type Pattern = { lean: string; count: number; total: number; never: string | null };

/** A pattern across the shelf, counted from each option's tags: the lean that most chosen options
 * share, when two or more do, and a lean only turned-down options had in each of them ("never the
 * one that pays debt off faster"). Null when no lean is shared. */
export function acrossShelf(
  decisions: readonly Pick<Decision, "options">[],
): Pattern | null {
  const counts = new Map<string, number>();
  for (const d of decisions) {
    for (const lean of new Set(d.options.filter((o) => o.chosen).flatMap((o) => o.leans))) {
      counts.set(lean, (counts.get(lean) ?? 0) + 1);
    }
  }
  let best: [string, number] | null = null;
  for (const [lean, count] of counts) {
    if (!best || count > best[1]) best = [lean, count];
  }
  if (!best || best[1] < 2) return null;
  const [lean, count] = best;
  const sharing = decisions.filter((d) => d.options.some((o) => o.chosen && o.leans.includes(lean)));
  const chosenLeans = new Set(decisions.flatMap((d) => d.options.filter((o) => o.chosen).flatMap((o) => o.leans)));
  const turnedDown = sharing.map(
    (d) => new Set(d.options.filter((o) => !o.chosen).flatMap((o) => o.leans)),
  );
  const first = turnedDown[0];
  const never =
    (first &&
      [...first].find((l) => !chosenLeans.has(l) && turnedDown.every((s) => s.has(l)))) ??
    null;
  return { lean, count, total: decisions.length, never };
}

/** The pattern in a sentence: "All 3 of 3 decisions chose the option that keeps cash on hand". */
export function patternWords(pattern: Pattern): { lead: string; lean: string; tail: string } {
  const lead =
    pattern.count === pattern.total
      ? `All ${pattern.count} of ${pattern.total} decisions chose the option that`
      : `${pattern.count} of ${pattern.total} decisions chose the option that`;
  const tail = pattern.never ? `, never the one that ${pattern.never}.` : ".";
  return { lead, lean: pattern.lean, tail };
}

// --- The open book -------------------------------------------------------------------------------

export type Bookmark = "decision" | "revisit" | "facts";

export const BOOKMARKS: readonly Bookmark[] = ["decision", "revisit", "facts"];

export function bookmarkOf(value: string | null): Bookmark {
  return value === "revisit" || value === "facts" ? value : "decision";
}

/** Where a book opens: "/decisions?book=<id>", at a bookmark other than the first if named. */
export function bookHref(id: string, mark: Bookmark = "decision"): string {
  const book = `/decisions?book=${encodeURIComponent(id)}`;
  return mark === "decision" ? book : `${book}&mark=${mark}`;
}

/** The three bookmarks' names, on one row: "The decision", "To revisit · 1", "Rests on 21 facts". */
export function bookmarkLabels(
  decision: Pick<Decision, "revisit" | "rests_on">,
): Record<Bookmark, string> {
  return {
    decision: "The decision",
    revisit: `To revisit · ${decision.revisit.length}`,
    facts: `Rests on ${plural(decision.rests_on.length, "fact")}`,
  };
}

export const NEXT_BOOKMARK: Record<Bookmark, { to: Bookmark; label: string }> = {
  decision: { to: "revisit", label: "Next: what has moved since" },
  revisit: { to: "facts", label: "Next: the facts it rests on" },
  facts: { to: "decision", label: "Back to the decision" },
};

/** An option's words without its letter, starting with a capital: "Keep it for the trip". */
export function optionWords(option: Pick<DecisionOption, "label">): string {
  const { words } = optionParts(option.label);
  return words.slice(0, 1).toUpperCase() + words.slice(1);
}

const flat = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

/** The reasoning Kako kept, when the household's own words don't already say it. */
export function whyLine(decision: Pick<Decision, "quote" | "reasoning">): string | null {
  if (!decision.reasoning.trim()) return null;
  if (decision.quote && flat(decision.quote).includes(flat(decision.reasoning))) return null;
  return decision.reasoning;
}

// --- What it rests on ----------------------------------------------------------------------------

const FACT_GROUPS: readonly [string, string][] = [
  ["income", "Income"],
  ["debt", "Debts"],
  ["expense", "Spending"],
  ["account", "Savings"],
  ["goal", "Goals"],
  ["household", "House rules"],
];

export type FactLine = {
  label: string | null; // what the value is, beside it; null when `value` says it all
  value: string; // "₱52,000.00", or "essential" for a yes or no
  from: string; // valid_from
  moved: boolean;
  now: { value: string | null; from_day: string | null } | null; // what holds instead, once moved
};

export type FactThing = { name: string; lines: FactLine[] };

export type FactGroup = { kind: string; label: string; count: number; things: FactThing[] };

/** A yes or no in words: "essential" or "not essential", from "essential (yes or no)". */
function yesNo(words: string, value: string): string | null {
  const match = /^(.*) \(yes or no\)$/.exec(words);
  if (!match?.[1]) return null;
  if (value === "yes") return match[1];
  if (value === "no") return `not ${match[1]}`;
  return null;
}

/** The facts a decision rests on, as cards by kind (income, debts, spending, savings, goals, the
 * household's own rules), each thing with its values. A moved fact carries what holds now, from the
 * decision's revisit list. */
export function factGroups(
  rests: readonly RestsOn[],
  revisit: readonly ChangedFact[] = [],
): FactGroup[] {
  const rank = new Map(FACT_GROUPS.map(([kind], i) => [kind, i]));
  const groups = new Map<string, FactGroup>();
  for (const r of rests) {
    let group = groups.get(r.kind);
    if (!group) {
      const label = FACT_GROUPS.find(([kind]) => kind === r.kind)?.[1] ?? r.kind;
      group = { kind: r.kind, label, count: 0, things: [] };
      groups.set(r.kind, group);
    }
    group.count += 1;
    // The household's rules are each their own line: their words are the label.
    const name = r.kind === "household" ? r.words.slice(0, 1).toUpperCase() + r.words.slice(1) : r.thing;
    let thing = group.things.find((t) => t.name === name);
    if (!thing) {
      thing = { name, lines: [] };
      group.things.push(thing);
    }
    const said = yesNo(r.words, r.value);
    const change = r.moved ? revisit.find((c) => c.title === r.title) : undefined;
    thing.lines.push({
      label: said !== null || r.kind === "household" ? null : r.words,
      value: said ?? r.value,
      from: r.valid_from,
      moved: r.moved,
      now: r.moved ? { value: change?.after ?? null, from_day: change?.from_day ?? null } : null,
    });
  }
  return [...groups.values()].sort((a, b) => (rank.get(a.kind) ?? 99) - (rank.get(b.kind) ?? 99));
}

/** The day every fact held from, when they all share one; null when they differ. */
export function sharedFrom(rests: readonly Pick<RestsOn, "valid_from">[]): string | null {
  const days = new Set(rests.map((r) => r.valid_from));
  const [only] = days;
  return days.size === 1 && only ? only : null;
}

/** A changed fact split into what it is about and what the value is, from the facts it rests on:
 * "Mara's salary" and "take-home pay a month". The title alone when none matches. */
export function changedParts(
  change: Pick<ChangedFact, "title">,
  rests: readonly Pick<RestsOn, "title" | "thing" | "words" | "kind">[],
): { thing: string; words: string | null } {
  const found = rests.find((r) => r.title === change.title);
  if (!found) return { thing: change.title, words: null };
  if (found.kind === "household") return { thing: "The household", words: found.words };
  return { thing: found.thing, words: found.words };
}
