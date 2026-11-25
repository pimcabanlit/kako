import assert from "node:assert/strict";
import { test } from "node:test";

import {
  byKind,
  byMonth,
  decidedLine,
  decisionStatus,
  eventHref,
  eventLine,
  monthWords,
  quoteOf,
  thingCard,
  valueState,
  windowWords,
} from "./history.ts";
import type { AttributeHistory, Thing, TimelineEvent, ValueAt } from "./types.ts";

function event(on: string, kind: string, ahead = false, ref: string | null = null): TimelineEvent {
  return {
    kind,
    on,
    ahead,
    title: `${kind} on ${on}`,
    detail: null,
    source: null,
    changes: [],
    ref,
    revisit: false,
    by: null,
  };
}

function value(v: string, state: ValueAt["state"], from: string, to: string | null = null): ValueAt {
  return {
    id: `${v}-${from}`,
    value: v,
    valid_from: from,
    valid_to: to,
    state,
    source: "From a statement",
    shared_on: null,
    reason: null,
  };
}

function thing(kind: string, name: string, attributes: AttributeHistory[]): Thing {
  return { id: name, name, kind, opened_on: null, closed_on: null, attributes };
}

test("a value's state in words and its colour", () => {
  assert.deepEqual(valueState("current"), { label: "Current", tone: "emerald" });
  assert.deepEqual(valueState("coming"), { label: "Coming", tone: "orange" });
  assert.deepEqual(valueState("past"), { label: "Past", tone: "plain" });
  assert.deepEqual(valueState("corrected"), { label: "Corrected", tone: "rose" });
  assert.deepEqual(valueState("odd"), { label: "odd", tone: "plain" });
});

test("when a value holds", () => {
  assert.equal(windowWords({ valid_from: "2026-12-01", valid_to: null }), "From Dec 1, 2026");
  assert.equal(
    windowWords({ valid_from: "2026-03-01", valid_to: "2026-12-01" }),
    "Mar 1, 2026 until Dec 1, 2026",
  );
});

test("where an event opens", () => {
  assert.equal(eventHref(event("2026-09-15", "plan", false, "p1")), "/plans/p1");
  assert.equal(eventHref(event("2026-09-15", "session", false, "s1")), "/sessions/s1");
  assert.equal(eventHref(event("2026-09-15", "decision", false, "d1")), "/decisions#decision-d1");
  assert.equal(eventHref(event("2026-09-15", "change", false, "x")), null);
  assert.equal(eventHref(event("2026-09-15", "plan")), null);
});

test("a decision's standing, its words and who chose", () => {
  assert.deepEqual(decisionStatus("active"), { label: "In force", tone: "emerald" });
  assert.deepEqual(decisionStatus("revised"), { label: "Revised", tone: "plain" });
  assert.deepEqual(decisionStatus("reversed"), { label: "Reversed", tone: "rose" });
  const reasoning = "Lia starts school and we want cash on hand.";
  assert.equal(quoteOf({ quote: null, reasoning }), null);
  assert.equal(quoteOf({ quote: " Lia starts school and  we want cash on hand. ", reasoning }), null);
  const said = "Let's split it. Lia starts school and we want cash on hand.";
  assert.equal(quoteOf({ quote: said, reasoning }), said);
  assert.equal(
    decidedLine({ decided_by: "Mara", session_title: "Session 2", on: "2026-09-15" }),
    "Decided by Mara in Session 2, Sep 15, 2026",
  );
  assert.equal(
    decidedLine({ decided_by: null, session_title: "Session 2", on: "2026-09-15" }),
    "Decided in Session 2, Sep 15, 2026",
  );
});

test("events by month, newest first, in the order given", () => {
  const job = event("2026-12-01", "life_event");
  const session = event("2026-11-20", "session");
  const statement = event("2026-11-15", "change");
  const decision = event("2026-10-18", "decision");
  assert.deepEqual(byMonth([job, session, statement, decision]), [
    { key: "2026-12", label: "December 2026", events: [job] },
    { key: "2026-11", label: "November 2026", events: [session, statement] },
    { key: "2026-10", label: "October 2026", events: [decision] },
  ]);
  assert.deepEqual(byMonth([]), []);
  assert.equal(monthWords("2026-03-01"), "March 2026");
  assert.equal(monthWords("soon"), "soon");
});

test("the line under an event's headline: when, what kind, who said yes", () => {
  const job = { ...event("2026-12-01", "life_event"), detail: "New job", by: "Mara" };
  assert.deepEqual(eventLine(job), ["Dec 1, 2026", "New job", "Approved by Mara"]);
  const choice = { ...event("2026-10-18", "decision"), detail: "Chose B", by: "Jun" };
  assert.deepEqual(eventLine(choice), ["Oct 18, 2026", "Decision", "Decided by Jun"]);
  const fact = {
    label: "replaced",
    title: "Credit card (balance)",
    before: null,
    after: "₱1",
    from_day: null,
  };
  const statement = { ...event("2026-11-15", "change"), changes: [fact, fact, fact], by: "Jun" };
  assert.deepEqual(eventLine(statement), ["Nov 15, 2026", "3 figures", "Approved by Jun"]);
  assert.deepEqual(eventLine({ ...statement, changes: [fact] })[1], "1 figure");
  const plan = { ...event("2026-12-01", "plan"), detail: "Proposed" };
  assert.deepEqual(eventLine(plan), ["Dec 1, 2026", "Plan, proposed"]);
  const session = { ...event("2026-11-20", "session"), detail: "2 turns" };
  assert.deepEqual(eventLine(session), ["Nov 20, 2026", "Session, 2 turns"]);
  const start = { ...event("2026-08-01", "start"), detail: "25 facts" };
  assert.deepEqual(eventLine(start), ["Aug 1, 2026", "Starting figures"]);
  const fixed = { ...event("2026-11-02", "correction"), by: "Mara" };
  assert.deepEqual(eventLine(fixed), ["Nov 2, 2026", "Correction", "Approved by Mara"]);
});

test("things by kind, in the order given", () => {
  const home = thing("household", "The household", []);
  const jun = thing("income", "Jun's salary", []);
  const mara = thing("income", "Mara's salary", []);
  const card = thing("debt", "Credit card", []);
  assert.deepEqual(byKind([home, jun, mara, card]), [
    { kind: "household", label: "The household", things: [home] },
    { kind: "income", label: "Income", things: [jun, mara] },
    { kind: "debt", label: "Debts", things: [card] },
  ]);
});

test("a thing's card: what it holds now, when it changed, what is coming", () => {
  const pay = (values: ValueAt[]): AttributeHistory => ({
    attribute: "income.amount",
    words: "take-home pay a month",
    values,
  });
  // Her new salary is coming: the card shows what holds now and when the change comes.
  const ahead = thingCard(
    thing("income", "Mara's salary", [
      pay([
        value("₱68,000.00", "coming", "2026-12-01"),
        value("₱52,000.00", "current", "2026-03-01", "2026-12-01"),
      ]),
    ]),
  );
  assert.deepEqual(ahead, {
    value: "₱52,000.00",
    words: "take-home pay a month",
    meta: "Since Mar 1, 2026",
    coming: "2026-12-01",
    corrected: false,
  });
  // Once it holds, the card says when it changed.
  const now = thingCard(
    thing("income", "Mara's salary", [
      pay([
        value("₱68,000.00", "current", "2026-12-01"),
        value("₱52,000.00", "past", "2026-03-01", "2026-12-01"),
      ]),
    ]),
  );
  assert.equal(now.value, "₱68,000.00");
  assert.equal(now.meta, "Changed Dec 1, 2026");
  assert.equal(now.coming, null);
  // Its first value shown, the rest left for the details; a correction is noted.
  const card = thingCard(
    thing("debt", "Credit card", [
      {
        attribute: "debt.balance",
        words: "balance",
        values: [
          value("₱76,880.00", "current", "2026-11-15"),
          value("₱80,000.00", "corrected", "2026-11-15"),
        ],
      },
      {
        attribute: "debt.rate",
        words: "interest rate",
        values: [value("3% a month", "current", "2026-03-01")],
      },
      {
        attribute: "debt.minimum",
        words: "minimum payment a month",
        values: [value("₱2,550.00", "current", "2026-03-01")],
      },
    ]),
  );
  assert.deepEqual([card.value, card.words], ["₱76,880.00", "balance"]);
  assert.equal(card.meta, "Changed Nov 15, 2026"); // the right balance took the wrong one's place
  assert.equal(card.corrected, true);
  assert.deepEqual(thingCard({ attributes: [] }), {
    value: null,
    words: "No values kept for it",
    meta: "",
    coming: null,
    corrected: false,
  });
});
