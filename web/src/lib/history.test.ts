import assert from "node:assert/strict";
import { test } from "node:test";

import {
  byDay,
  decidedLine,
  decisionStatus,
  eventHref,
  quoteOf,
  valueState,
  windowWords,
} from "./history.ts";
import type { TimelineEvent } from "./types.ts";

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
  };
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

test("events by day, what is ahead apart, in the order given", () => {
  const job = event("2026-12-01", "life_event", true);
  const plan = event("2026-12-01", "plan", true);
  const session = event("2026-11-20", "session");
  const statement = event("2026-11-15", "change");
  const decision = event("2026-11-15", "decision");
  const { ahead, past } = byDay([job, plan, session, statement, decision]);
  assert.deepEqual(ahead, [{ on: "2026-12-01", events: [job, plan] }]);
  assert.deepEqual(past, [
    { on: "2026-11-20", events: [session] },
    { on: "2026-11-15", events: [statement, decision] },
  ]);
  assert.deepEqual(byDay([]), { ahead: [], past: [] });
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
