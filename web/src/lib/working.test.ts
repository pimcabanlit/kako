import assert from "node:assert/strict";
import { test } from "node:test";

import type { Step } from "./types.ts";
import {
  describeTool,
  groupSteps,
  shortInput,
  summarize,
  summaryLine,
  toneOf,
} from "./working.ts";

function step(seq: number, agent: string, tool: string, outcome = "ok"): Step {
  return {
    seq,
    agent,
    tool,
    input_summary: "{}",
    result_summary: "",
    outcome,
    at: "2026-11-25T00:00:00Z",
  };
}

// A turn shaped like the demo's session 2: two specialists asked in parallel, their steps logged
// before the asks that called them end, then the orchestrator's own what-if and its answer, sent
// back once by the checks.
const turn: Step[] = [
  step(1, "savings", "run_what_if"),
  step(2, "debt", "run_what_if"),
  step(3, "savings", "run_what_if"),
  step(4, "debt", "run_what_if"),
  step(5, "savings", "submit_proposal"),
  step(6, "debt", "submit_proposal"),
  step(7, "orchestrator", "ask_debt"),
  step(8, "orchestrator", "ask_savings"),
  step(9, "orchestrator", "run_what_if"),
  step(10, "orchestrator", "submit_answer", "error"),
  step(11, "orchestrator", "get_figures", "error"),
  step(12, "orchestrator", "get_figures"),
  step(13, "orchestrator", "submit_answer"),
];

test("each specialist's steps sit under the ask they answered", () => {
  const groups = groupSteps([...turn].reverse()); // the order they arrive in doesn't matter
  assert.deepEqual(
    groups.map((g) => [g.step?.seq ?? null, g.specialist, g.children.map((c) => c.seq)]),
    [
      [7, "debt", [2, 4, 6]],
      [8, "savings", [1, 3, 5]],
      [9, null, []],
      [10, null, []],
      [11, null, []],
      [12, null, []],
      [13, null, []],
    ],
  );
});

test("a specialist asked twice: each ask takes the steps before it", () => {
  const groups = groupSteps([
    step(1, "debt", "run_what_if"),
    step(2, "orchestrator", "ask_debt"),
    step(3, "debt", "run_what_if"),
    step(4, "debt", "submit_proposal"),
    step(5, "orchestrator", "ask_debt"),
  ]);
  assert.deepEqual(
    groups.map((g) => [g.step?.seq, g.children.map((c) => c.seq)]),
    [
      [2, [1]],
      [5, [3, 4]],
    ],
  );
});

test("a specialist still working shows as its own group until its ask ends", () => {
  const groups = groupSteps([step(1, "budget", "get_figures"), step(2, "debt", "run_what_if")]);
  assert.deepEqual(
    groups.map((g) => [g.step, g.specialist, g.children.length]),
    [
      [null, "budget", 1],
      [null, "debt", 1],
    ],
  );
});

test("the summary counts what-ifs, send-backs and refusals", () => {
  const summary = summarize([...turn, step(14, "orchestrator", "run_what_if", "rejected")]);
  assert.deepEqual(summary, {
    steps: 14,
    agents: ["savings", "debt"],
    whatIfs: 5,
    sentBack: 1,
    refused: 1,
    errors: 1,
  });
  assert.equal(
    summaryLine(summary),
    "14 steps · savings and debt specialists · 5 what-ifs · 1 sent back · 1 refused · 1 error",
  );
  assert.equal(summaryLine(summarize([step(1, "orchestrator", "propose_change")])), "1 step");
});

test("tones and words", () => {
  assert.equal(toneOf(step(1, "orchestrator", "submit_answer", "error")), "sent_back");
  assert.equal(toneOf(step(1, "orchestrator", "get_figures", "error")), "error");
  assert.equal(toneOf(step(1, "orchestrator", "run_what_if", "rejected")), "refused");
  assert.equal(describeTool("ask_savings"), "Asked the savings specialist");
  assert.equal(describeTool("search_memory"), "Searched Meko");
  assert.equal(describeTool("something_new"), "something_new");
  assert.equal(
    shortInput('{"allocations": [{"entity": "debt:credit-card", "amount": "rest"}]}'),
    "allocations: entity: debt:credit-card, amount: rest",
  );
  assert.equal(shortInput("x".repeat(200), 10), "xxxxxxxxx…");
});
