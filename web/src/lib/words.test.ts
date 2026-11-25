import assert from "node:assert/strict";
import { test } from "node:test";

import type { Proposal } from "./types.ts";
import {
  answerKindWords,
  attributeWords,
  initials,
  lifeEvent,
  proposalTitle,
  sourceDetail,
  sourceKind,
} from "./words.ts";

function proposal(kind: string, extra: Partial<Proposal> = {}): Proposal {
  return {
    id: "p1",
    kind,
    status: "pending",
    shown: "",
    change: null,
    explanation: "",
    payload: {},
    from_dreaming: false,
    created_at: "2026-11-20T00:00:00Z",
    decided_by: null,
    decided_at: null,
    evidence: [],
    written: [],
    ...extra,
  };
}

test("attributes and sources in plain words; violet only for Meko", () => {
  assert.equal(attributeWords("income.monthly_net"), "take-home pay a month");
  assert.equal(attributeWords("new.attribute"), "new.attribute");
  assert.equal(sourceKind({ kind: "memory", ref: "M1", shown: "" }).tone, "meko");
  assert.equal(sourceKind({ kind: "knowledge", ref: "K1", shown: "" }).tone, "meko");
  for (const kind of ["figure", "fact", "decision", "conversation", "calculation", "history", "document", "other"])
    assert.notEqual(sourceKind({ kind, ref: "", shown: "" }).tone, "meko", kind);
  assert.equal(sourceKind({ kind: "document", ref: "doc:sss", shown: "" }).label, "Document");
  assert.equal(sourceKind({ kind: "calculation", ref: "calc:C1", shown: "" }).label, "Calculated");
});

test("what a source chip shows after its kind", () => {
  assert.equal(
    sourceDetail({ kind: "document", ref: "doc:general-guidance", shown: "# General guidance\n..." }),
    "general guidance",
  );
  assert.equal(sourceDetail({ kind: "figure", ref: "figure:x", shown: "₱9,050.00" }), "₱9,050.00");
  assert.equal(sourceDetail({ kind: "calculation", ref: "calc:C1", shown: "a\nb" }), "a");
  assert.equal(sourceDetail({ kind: "conversation", ref: "said", shown: "my words" }), null);
  assert.equal(sourceDetail({ kind: "decision", ref: "decision:D1", shown: "D1" }), null);
});

test("kinds of answer in words", () => {
  assert.equal(answerKindWords("simulate"), "A what-if, nothing saved");
  assert.equal(answerKindWords("look_up"), "Looked up in your records");
  assert.equal(answerKindWords("new_kind"), "new kind");
  assert.equal(answerKindWords(null), null);
  assert.equal(answerKindWords(undefined), null);
});

test("proposal titles and life events", () => {
  const salary = proposal("replace_fact", {
    change: {
      subject: "Mara's salary",
      attribute: "income.monthly_net",
      before: "₱52,000.00",
      after: "₱68,000.00",
      from_day: "Dec 1, 2026",
    },
  });
  assert.equal(proposalTitle(salary), "Mara's salary: take-home pay a month");
  const job = proposal("life_event", {
    payload: { kind: "new_job", occurs_on: "2026-12-01", description: "Mara got a new job" },
  });
  assert.equal(proposalTitle(job), "Life event: new job");
  assert.deepEqual(lifeEvent(job), { description: "Mara got a new job", on: "2026-12-01" });
  assert.equal(lifeEvent(salary), null);
  assert.equal(initials("Mara"), "M");
  assert.equal(initials("Ana Reyes"), "AR");
});
