import assert from "node:assert/strict";
import { test } from "node:test";

import {
  acrossShelf,
  bookHref,
  bookmarkLabels,
  bookmarkOf,
  changedParts,
  coverIcon,
  coverOf,
  factGroups,
  onShelf,
  optionWords,
  patternWords,
  sharedFrom,
  shelfChips,
  whyLine,
} from "./shelf.ts";
import type { ChangedFact, Decision, DecisionOption, RestsOn } from "./types.ts";

const SALARY = "Mara's salary (take-home pay a month)";

function rest(title: string, thing: string, kind: string, words: string, value: string, moved = false): RestsOn {
  return { title, thing, kind, words, value, valid_from: "2026-03-01", moved };
}

const RESTS: RestsOn[] = [
  rest("Car loan (interest rate)", "Car loan", "debt", "interest rate", "9% a year"),
  rest("Food (amount a month)", "Food", "expense", "amount a month", "₱20,000.00"),
  rest("Food (essential (yes or no))", "Food", "expense", "essential (yes or no)", "yes"),
  rest("Eating out (essential (yes or no))", "Eating out", "expense", "essential (yes or no)", "no"),
  rest(SALARY, "Mara's salary", "income", "take-home pay a month", "₱52,000.00", true),
  rest("The household's debt payoff strategy", "The household", "household", "debt payoff strategy", "avalanche"),
];

const RAISE: ChangedFact = {
  label: "replaced",
  title: SALARY,
  before: "₱52,000.00",
  after: "₱68,000.00",
  from_day: "Dec 1, 2026",
};

function option(label: string, chosen: boolean, leans: string[], reason: string | null = null): DecisionOption {
  return { label, chosen, reason, leans };
}

function decision(over: Partial<Decision> = {}): Decision {
  return {
    id: "d3",
    question: "Should the bonus go to the card or the family trip?",
    chosen: "B: keep it for the trip",
    reasoning: "Keep cash for the family trip.",
    quote: "Keep cash for the family trip.",
    said_by: "Jun",
    decided_by: "Jun",
    decided_at: "2026-10-18T02:00:00Z",
    session_id: "s3",
    session_title: "Session 3",
    on: "2026-10-18",
    status: "active",
    valid_to: null,
    replaced_by: null,
    outcome: null,
    plan_id: null,
    options: [
      option("B: keep it for the trip", true, ["keeps cash on hand"]),
      option("A: all on the card", false, ["pays debt off faster"], "Keep cash for the family trip."),
    ],
    rests_on: RESTS,
    revisit: [RAISE],
    ...over,
  };
}

test("the shelf's chips count what each view shows; revised takes in reversed ones too", () => {
  const all = [
    decision(),
    decision({ id: "d2", revisit: [] }),
    decision({ id: "d1", status: "revised", revisit: [] }),
    decision({ id: "d0", status: "reversed", revisit: [] }),
  ];
  assert.deepEqual(
    shelfChips(all).map((c) => c.label),
    ["All 4", "To revisit 1", "In force 2", "Revised 2"],
  );
  assert.equal(onShelf(all[2]!, "in-force"), false);
  assert.equal(onShelf(all[3]!, "revised"), true);
  assert.equal(onShelf(all[0]!, "revisit"), true);
});

test("covers follow the session, oldest first, round the three covers", () => {
  const covers = coverOf([
    decision({ id: "d3", session_id: "s3", on: "2026-10-18" }),
    decision({ id: "d2b", session_id: "s2", on: "2026-09-15" }),
    decision({ id: "d2", session_id: "s2", on: "2026-09-15" }),
    decision({ id: "d1", session_id: "s1", on: "2026-08-15" }),
    decision({ id: "d4", session_id: "s4", on: "2026-12-01" }),
  ]);
  assert.deepEqual(
    ["d1", "d2", "d2b", "d3", "d4"].map((id) => covers.get(id)),
    [0, 1, 1, 2, 0],
  );
});

test("a cover's picture comes from the choice first, then the question", () => {
  assert.equal(coverIcon(decision()), "trip");
  assert.equal(
    coverIcon({ question: "How hard should we pay down the credit card?", chosen: "B: split" }),
    "card",
  );
  assert.equal(
    coverIcon({ question: "Should we pay the car loan early or keep a bigger buffer?", chosen: "B: bigger buffer" }),
    "buffer",
  );
  assert.equal(coverIcon({ question: "What now?", chosen: "A: wait" }), "book");
});

test("across the shelf: the lean every chosen option shares, and the one only turned down", () => {
  const three = [decision(), decision({ id: "d2" }), decision({ id: "d1" })];
  const pattern = acrossShelf(three);
  assert.deepEqual(pattern, {
    lean: "keeps cash on hand",
    count: 3,
    total: 3,
    never: "pays debt off faster",
  });
  const words = patternWords(pattern!);
  assert.equal(
    `${words.lead} ${words.lean}${words.tail}`,
    "All 3 of 3 decisions chose the option that keeps cash on hand, never the one that pays debt off faster.",
  );
});

test("across the shelf says nothing for one decision, and no 'never' once a choice leaned that way", () => {
  assert.equal(acrossShelf([decision()]), null);
  const other = decision({
    id: "d1",
    options: [
      option("A: pay it off", true, ["pays debt off faster"]),
      option("B: keep cash", false, ["keeps cash on hand"]),
    ],
  });
  const pattern = acrossShelf([decision(), decision({ id: "d2" }), other]);
  assert.equal(pattern?.count, 2);
  assert.equal(pattern?.never, null);
  const words = patternWords(pattern!);
  assert.equal(`${words.lead} ${words.lean}${words.tail}`, "2 of 3 decisions chose the option that keeps cash on hand.");
  assert.equal(acrossShelf([decision({ options: [option("A: x", true, [])] }), decision({ id: "d2", options: [option("A: x", true, [])] })]), null);
});

test("a book opens at a bookmark from the address; anything else is the first", () => {
  assert.equal(bookHref("d3"), "/decisions?book=d3");
  assert.equal(bookHref("d3", "revisit"), "/decisions?book=d3&mark=revisit");
  assert.equal(bookmarkOf("facts"), "facts");
  assert.equal(bookmarkOf(null), "decision");
  assert.equal(bookmarkOf("cover"), "decision");
});

test("the three bookmarks' names", () => {
  assert.deepEqual(bookmarkLabels(decision()), {
    decision: "The decision",
    revisit: "To revisit · 1",
    facts: "Rests on 6 facts",
  });
  assert.equal(bookmarkLabels(decision({ revisit: [], rests_on: [RESTS[0]!] })).facts, "Rests on 1 fact");
});

test("options lose their letters; the reasoning shows only when their words don't say it", () => {
  assert.equal(optionWords({ label: "B: keep it for the trip" }), "Keep it for the trip");
  assert.equal(optionWords({ label: "split" }), "Split");
  assert.equal(whyLine(decision()), null);
  assert.equal(
    whyLine({ quote: "We'll take the split. Lia starts school and we want cash on hand.", reasoning: "Lia starts school and we want cash on hand." }),
    null,
  );
  assert.equal(whyLine({ quote: null, reasoning: "Cash on hand." }), "Cash on hand.");
  assert.equal(whyLine({ quote: "Go.", reasoning: "Cash on hand." }), "Cash on hand.");
});

test("the facts it rests on, as cards by kind, a yes or no in words, the moved one with what holds now", () => {
  const groups = factGroups(RESTS, [RAISE]);
  assert.deepEqual(
    groups.map((g) => [g.label, g.count]),
    [["Income", 1], ["Debts", 1], ["Spending", 3], ["House rules", 1]],
  );
  const [income, debts, spending, rules] = groups;
  assert.deepEqual(income!.things[0], {
    name: "Mara's salary",
    lines: [
      {
        label: "take-home pay a month",
        value: "₱52,000.00",
        from: "2026-03-01",
        moved: true,
        now: { value: "₱68,000.00", from_day: "Dec 1, 2026" },
      },
    ],
  });
  assert.deepEqual(debts!.things[0]!.lines[0]!.label, "interest rate");
  assert.deepEqual(
    spending!.things.map((t) => [t.name, t.lines.map((l) => [l.label, l.value])]),
    [
      ["Food", [["amount a month", "₱20,000.00"], [null, "essential"]]],
      ["Eating out", [[null, "not essential"]]],
    ],
  );
  assert.deepEqual(rules!.things[0], {
    name: "Debt payoff strategy",
    lines: [{ label: null, value: "avalanche", from: "2026-03-01", moved: false, now: null }],
  });
});

test("one shared day for every fact, or none", () => {
  assert.equal(sharedFrom(RESTS), "2026-03-01");
  assert.equal(sharedFrom([...RESTS, { valid_from: "2026-09-01" }]), null);
  assert.equal(sharedFrom([]), null);
});

test("a change is split into its thing and words from the facts it rests on", () => {
  assert.deepEqual(changedParts(RAISE, RESTS), { thing: "Mara's salary", words: "take-home pay a month" });
  assert.deepEqual(changedParts({ title: "Something else" }, RESTS), { thing: "Something else", words: null });
});
