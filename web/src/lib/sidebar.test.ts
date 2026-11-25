import assert from "node:assert/strict";
import { test } from "node:test";

import { flipped, sidebarFrom } from "./sidebar.ts";

test("only a saved 'collapsed' collapses the sidebar", () => {
  assert.equal(sidebarFrom("collapsed"), "collapsed");
  for (const saved of ["open", null, undefined, "", "Collapsed", "true", "<script>"]) {
    assert.equal(sidebarFrom(saved), "open", String(saved));
  }
});

test("the button switches to the other state and back", () => {
  assert.equal(flipped("open"), "collapsed");
  assert.equal(flipped("collapsed"), "open");
  assert.equal(flipped(flipped("open")), "open");
});
