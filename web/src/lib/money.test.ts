import assert from "node:assert/strict";
import { test } from "node:test";

import {
  donutArcs,
  milestoneTitle,
  moneyHref,
  momentWhen,
  monthYear,
  ROWS_SHOWN,
  rowsShown,
  signedAmount,
  viewOf,
} from "./money.ts";

test("the view comes from the address; anything else is the overview", () => {
  assert.equal(viewOf("debts"), "debts");
  assert.equal(viewOf("worth"), "worth");
  assert.equal(viewOf(null), "overview");
  assert.equal(viewOf("everything"), "overview");
  assert.equal(moneyHref("overview"), "/money");
  assert.equal(moneyHref("plan"), "/money?view=plan");
});

test("money in reads as it is, money out with a minus, an unknown amount says so", () => {
  assert.equal(signedAmount({ kind: "in", amount: "₱68,000.00" }), "₱68,000.00");
  assert.equal(signedAmount({ kind: "need", amount: "₱40,000.00" }), "−₱40,000.00");
  assert.equal(signedAmount({ kind: "savings", amount: "₱5,050.00" }), "−₱5,050.00");
  assert.equal(signedAmount({ kind: "want", amount: null }), "unknown");
});

test("months and moments in words", () => {
  assert.equal(monthYear("2027-08-01"), "Aug 2027");
  const day = (iso: string) => `day ${iso}`;
  assert.equal(momentWhen({ on: "2026-12-01", month_only: true }, day), "December 2026");
  assert.equal(momentWhen({ on: "2026-12-01", month_only: false }, day), "day 2026-12-01");
  assert.equal(milestoneTitle({ kind: "debt_paid", name: "Credit card" }), "Credit card paid off");
  assert.equal(milestoneTitle({ kind: "emergency_fund", name: "Emergency fund" }), "Emergency fund at its target");
  assert.equal(milestoneTitle({ kind: "goal_reached", name: "House fund" }), "House fund reached");
});

test("a long schedule shows its first year until asked for all of it", () => {
  const rows = Array.from({ length: 22 }, (_, i) => ({ month: i + 1 }));
  assert.equal(rowsShown(rows, false).length, ROWS_SHOWN);
  assert.equal(rowsShown(rows, true).length, 22);
  assert.equal(rowsShown(rows.slice(0, 7), false).length, 7);
});

test("the donut's segments follow each part's share, clockwise from twelve o'clock", () => {
  const arcs = donutArcs([
    { key: "needs", amount: 7_000_000 },
    { key: "wants", amount: 600_000 },
    { key: "debt", amount: 2_495_000 },
    { key: "savings", amount: 1_505_000 },
    { key: "unplanned", amount: 0 },
  ]);
  assert.deepEqual(arcs.map((a) => a.key), ["needs", "wants", "debt", "savings"]);
  assert.equal(arcs[0]!.start, 0);
  assert.equal(arcs.at(-1)!.end, 1);
  for (let i = 1; i < arcs.length; i++) assert.equal(arcs[i]!.start, arcs[i - 1]!.end);
  assert.ok(Math.abs(arcs[0]!.end - 7_000_000 / 11_600_000) < 1e-12);
  // Needs is more than half the pay, so its arc takes the long way round.
  assert.match(arcs[0]!.path, /^M100 0A100 100 0 1 1 /);
  assert.match(arcs[1]!.path, /A100 100 0 0 1 /);
});

test("one part is a whole ring; nothing at all is no ring", () => {
  const [ring] = donutArcs([{ key: "needs", amount: 5 }]);
  assert.equal(ring!.start, 0);
  assert.equal(ring!.end, 1);
  assert.equal(ring!.path.split("M").length - 1, 2);
  assert.deepEqual(donutArcs([{ key: "needs", amount: 0 }]), []);
  assert.deepEqual(donutArcs([]), []);
});
