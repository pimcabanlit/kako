import assert from "node:assert/strict";
import { test } from "node:test";

import { blocks, count, formatDay, splitLabel, titleFrom, usd } from "./text.ts";

test("a reply in paragraphs and lists", () => {
  const reply =
    "Mara’s new job gives you more room.\n\nHere is the trade-off:\n- The split keeps building cash.\n- All on the card clears it in 3 months.\n\nWhat changed: see below.";
  assert.deepEqual(blocks(reply), [
    { kind: "p", text: "Mara’s new job gives you more room." },
    { kind: "p", text: "Here is the trade-off:" },
    {
      kind: "ul",
      items: ["The split keeps building cash.", "All on the card clears it in 3 months."],
    },
    { kind: "p", text: "What changed: see below." },
  ]);
  assert.deepEqual(blocks("one\ntwo"), [{ kind: "p", text: "one two" }]);
  assert.deepEqual(blocks(""), []);
  // A minus sign before a number is not a list.
  assert.deepEqual(blocks("-₱500 a month"), [{ kind: "p", text: "-₱500 a month" }]);
});

test("household dates, titles, money and counts", () => {
  assert.equal(formatDay("2026-09-15"), "Sep 15, 2026");
  assert.equal(formatDay("2026-12-01"), "Dec 1, 2026");
  assert.equal(formatDay("soon"), "soon");
  assert.equal(titleFrom("  How hard should we\npay down the card?  "), "How hard should we pay down the card?");
  assert.equal(
    titleFrom("Mara here. How hard should we pay down the credit card? Jun thinks ₱4,000 is enough"),
    "Mara here. How hard should we pay down the credit card…",
  );
  assert.equal(titleFrom("   "), "New session");
  assert.equal(usd("0.000000"), "US$0");
  assert.equal(usd("0.004512"), "US$0.0045");
  assert.equal(usd("1.284"), "US$1.28");
  assert.equal(count(73656), "73,656");
  assert.deepEqual(splitLabel("To revisit: “Should we…” (Session 1)"), {
    label: "To revisit",
    text: "“Should we…” (Session 1)",
  });
  assert.deepEqual(splitLabel("Emergency fund: ₱1 → ₱2"), {
    label: null,
    text: "Emergency fund: ₱1 → ₱2",
  });
});

test("what-changed lines and option labels in parts", async () => {
  const { optionParts, parseChange } = await import("./text.ts");
  assert.deepEqual(parseChange("Take-home pay a month, all incomes: ₱100,000.00 → ₱116,000.00"), {
    label: "Take-home pay a month, all incomes",
    before: "₱100,000.00",
    after: "₱116,000.00",
  });
  assert.deepEqual(parseChange("13th-month pay this December: none → ₱48,000.00"), {
    label: "13th-month pay this December",
    before: "none",
    after: "₱48,000.00",
  });
  assert.equal(parseChange("Nothing moved"), null);
  assert.deepEqual(optionParts("A: all extra on the card"), { letter: "A", words: "all extra on the card" });
  assert.deepEqual(optionParts("Keep going"), { letter: null, words: "Keep going" });
});
