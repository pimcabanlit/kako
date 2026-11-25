import assert from "node:assert/strict";
import { test } from "node:test";

import {
  allowanceWords,
  fill,
  modeWords,
  outcomeWords,
  pct,
  pointsBetween,
  usd4,
  whole,
} from "./metrics.ts";

test("costs, shares and counts as the screen writes them", () => {
  assert.equal(usd4("0.045246"), "US$0.0452");
  assert.equal(usd4("0.617581"), "US$0.6176");
  assert.equal(usd4("x"), "US$x");
  assert.equal(pct("93.3"), "93.3%");
  assert.equal(pct(88), "88%");
  assert.equal(pct(null), "Not yet");
  assert.equal(whole("51028"), "51,028");
  assert.equal(whole(648722), "648,722");
});

test("a meter's fill stays between 0 and 100", () => {
  assert.equal(fill("81.4"), 81.4);
  assert.equal(fill(null), 0);
  assert.equal(fill("140"), 100);
  assert.equal(fill("-2"), 0);
  assert.equal(fill("n/a"), 0);
});

test("the difference between two scores, in points", () => {
  assert.equal(pointsBetween("81.4", "59.3"), "+22.1 points");
  assert.equal(pointsBetween("59.3", "81.4"), "−22.1 points");
  assert.equal(pointsBetween("90.7", "90.7"), "same");
});

test("words for allowances, runs and gap outcomes", () => {
  assert.equal(allowanceWords("context_search"), "Context searches");
  assert.equal(allowanceWords("something_new"), "something_new");
  assert.equal(modeWords("replay"), "replayed from its recording");
  assert.equal(modeWords("record"), "recorded on Foundry");
  assert.deepEqual(outcomeWords("improved"), { label: "Improved", tone: "emerald" });
  assert.deepEqual(outcomeWords(null), { label: "Not replayed yet", tone: "plain" });
});
