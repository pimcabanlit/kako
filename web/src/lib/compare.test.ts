import assert from "node:assert/strict";
import { test } from "node:test";

import { cardRows, changeTone, isTotal, moved, optionIndex, rolledNote } from "./compare.ts";
import type { CompareCell, CompareRow } from "./types.ts";

const cell = (value: string, change: string | null = null, direction: CompareCell["direction"] = "none"): CompareCell => ({
  value,
  note: null,
  change,
  direction,
});

const row = (kind: CompareRow["kind"], label: string, on_card: boolean, before: string, ...options: CompareCell[]): CompareRow => ({
  key: kind,
  kind,
  label,
  on_card,
  before: cell(before),
  options,
});

const C = {
  options: [
    { label: "A: all extra on the card", each_month: "₱9,050.00 a month to the Credit card" },
    { label: "B: split it", each_month: "₱4,000.00 a month to the Credit card" },
  ],
  rows: [
    row("debt_paid", "Credit card paid off", true, "Aug 15, 2030", cell("Jun 15, 2027", "38 months sooner", "better"), cell("Feb 15, 2028", "30 months sooner", "better")),
    row("debt_interest", "Credit card interest", false, "₱111,635.47", cell("₱12,460.10"), cell("₱24,303.62")),
    row("emergency_fund", "Emergency fund at its target", true, "never", cell("never", "no change", "same"), cell("Sep 15, 2027", "reached in 12 months", "better")),
    row("interest_total", "Interest on every debt", true, "₱178,005.51", cell("₱58,378.07", "₱119,627.44 less", "better")),
  ],
};

test("better is emerald, worse is rose, the same is plain, and no direction has no chip", () => {
  assert.equal(changeTone("better"), "chip-emerald");
  assert.equal(changeTone("worse"), "chip-rose");
  assert.equal(changeTone("same"), "");
  assert.equal(changeTone("none"), null);
});

test("an option's card shows only the rows meant for cards, from its own column", () => {
  assert.equal(optionIndex(C, "B: split it"), 1);
  assert.equal(optionIndex(C, "C: something else"), -1);
  const b = cardRows(C, "B: split it");
  assert.deepEqual(
    b.map((r) => [r.label, r.before.value, r.after.value, r.after.change]),
    [
      ["Credit card paid off", "Aug 15, 2030", "Feb 15, 2028", "30 months sooner"],
      ["Emergency fund at its target", "never", "Sep 15, 2027", "reached in 12 months"],
    ],
  );
  // A row missing the option's cell is left out rather than shown empty.
  assert.equal(cardRows(C, "A: all extra on the card").length, 3);
  assert.deepEqual(cardRows(C, "C: something else"), []);
});

test("a value that didn't move isn't struck through", () => {
  const [card, fund] = cardRows(C, "A: all extra on the card").slice(0, 2);
  assert.equal(moved(card), true);
  assert.equal(moved(fund), false);
  assert.equal(isTotal({ kind: "interest_total" }), true);
  assert.equal(isTotal({ kind: "debt_interest" }), false);
});

test("a rolled-in payment says where it came from", () => {
  assert.equal(rolledNote({ rolled_in: "₱11,600.00", rolled_from: "Credit card" }), "+₱11,600.00 from the Credit card");
  assert.equal(rolledNote({ rolled_in: "₱11,600.00", rolled_from: null }), "+₱11,600.00 rolled in");
  assert.equal(rolledNote({ rolled_in: null, rolled_from: null }), null);
});
