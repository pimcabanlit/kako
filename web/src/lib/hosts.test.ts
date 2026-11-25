import assert from "node:assert/strict";
import { test } from "node:test";

import { hostName, isLoopbackHost } from "./hosts.ts";

test("a loopback Host is allowed, with or without its port", () => {
  for (const host of ["localhost", "localhost:3000", "127.0.0.1:3000", "[::1]:3000", "LOCALHOST:3000"]) {
    assert.equal(isLoopbackHost(host), true, host);
  }
});

test("any other Host is refused, as is none", () => {
  for (const host of ["evil.example", "evil.example:3000", "10.0.0.5:3000", "localhost.evil.example", "127.0.0.1.nip.io", "[::2]:3000", ""]) {
    assert.equal(isLoopbackHost(host), false, host);
  }
  assert.equal(isLoopbackHost(null), false);
});

test("the name is read without its port", () => {
  assert.equal(hostName("[::1]:3000"), "[::1]");
  assert.equal(hostName(" Example.com:80 "), "example.com");
});
