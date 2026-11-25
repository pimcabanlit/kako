import assert from "node:assert/strict";
import { test } from "node:test";

import { landed, mayHaveLanded } from "./turns.ts";
import type { KeptTurn, RunningTurn, SessionTurns } from "./types.ts";

const ASK = "Now that Mara has the new job, how fast can we clear the credit card?";

function kept(seed: string, message: string): KeptTurn {
  return { seed, message } as KeptTurn;
}

function session(turns: KeptTurn[], running: RunningTurn | null = null): SessionTurns {
  return { session: {} as SessionTurns["session"], turns, running };
}

test("a dropped connection or a proxy's 500 or 504 may still have been kept", () => {
  for (const status of [0, 500, 504]) assert.equal(mayHaveLanded(status), true, String(status));
  for (const status of [400, 404, 409, 422, 429, 502, 503]) {
    assert.equal(mayHaveLanded(status), false, String(status));
  }
});

test("the turn kept since the request is found by its message", () => {
  const now = session([kept("t1", "Hello"), kept("t2", ASK)]);
  assert.deepEqual(landed(["t1"], now, ASK), { kind: "kept", seed: "t2" });
});

test("an earlier turn with the same words is not this one", () => {
  const now = session([kept("t1", ASK)]);
  assert.deepEqual(landed(["t1"], now, ASK), { kind: "lost" });
});

test("a turn still running is waited for, and another message's is not", () => {
  const running = { seed: "t2", message: ASK } as RunningTurn;
  assert.deepEqual(landed(["t1"], session([kept("t1", "Hello")], running), ASK), {
    kind: "running",
  });
  assert.deepEqual(landed(["t1"], session([kept("t1", "Hello")], running), "Other"), {
    kind: "lost",
  });
});

test("nothing new means the turn was not kept", () => {
  assert.deepEqual(landed([], session([]), ASK), { kind: "lost" });
});
