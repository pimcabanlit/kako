import assert from "node:assert/strict";
import { test } from "node:test";

import {
  builtFrom,
  checkTally,
  factsBehind,
  millis,
  planStatus,
  versionLabel,
} from "./plan.ts";
import type { PlanSummary } from "./types.ts";

test("a plan's status in the household's words and its colour", () => {
  assert.deepEqual(planStatus("proposed"), { label: "Proposed", tone: "gold" });
  assert.deepEqual(planStatus("accepted"), { label: "Current", tone: "emerald" });
  assert.deepEqual(planStatus("replaced"), { label: "Replaced", tone: "plain" });
  assert.deepEqual(planStatus("odd"), { label: "odd", tone: "plain" });
});

test("the version picker's label", () => {
  const p: PlanSummary = {
    id: "p",
    version: 2,
    status: "accepted",
    session_id: "s",
    session_title: "Session 4",
    created_at: "2026-11-25T00:00:00Z",
    as_of: "2026-12-01",
    recommended_option: null,
    options: 2,
  };
  assert.equal(versionLabel(p), "v2 · Dec 1, 2026 · Current");
});

test("what a figure was built from", () => {
  assert.equal(builtFrom({ inputs: ["a"], facts: ["f", "g"] }), "1 figure and 2 facts");
  assert.equal(builtFrom({ inputs: [], facts: ["f"] }), "1 fact");
  assert.equal(builtFrom({ inputs: ["a", "b"], facts: [] }), "2 figures");
  assert.equal(builtFrom({ inputs: [], facts: [] }), null);
});

test("the facts behind the cited figures, each once, through their inputs", () => {
  const figures = {
    payoff: { inputs: ["surplus"], facts: ["balance", "rate"] },
    surplus: { inputs: ["income", "payoff"], facts: ["rate"] }, // a loop is walked once
    income: { inputs: [], facts: ["salary"] },
    runway: { inputs: ["income"], facts: ["savings"] },
  };
  assert.deepEqual(factsBehind(["payoff", "runway"], figures), [
    "balance",
    "rate",
    "savings",
    "salary",
  ]);
  assert.deepEqual(factsBehind(["missing"], figures), []);
  assert.deepEqual(factsBehind([], figures), []);
});

test("the number check's tally", () => {
  const checks = [
    { text: "a", result: "pass", numbers: [{ text: "₱1", matched: "x" }] },
    {
      text: "b",
      result: "fail",
      numbers: [
        { text: "₱2", matched: "y" },
        { text: "₱3", matched: null },
      ],
    },
  ];
  assert.deepEqual(checkTally(checks), { numbers: 3, matched: 2, flagged: 1 });
  assert.deepEqual(checkTally([]), { numbers: 0, matched: 0, flagged: 0 });
});

test("a Meko call's time", () => {
  assert.equal(millis(552), "552 ms");
  assert.equal(millis(1250), "1,250 ms");
  assert.equal(millis(null), null);
});
