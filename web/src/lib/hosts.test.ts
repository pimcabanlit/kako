import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";

import { hostName, isLoopbackHost, isPublicPicture, PUBLIC_PICTURES } from "./hosts.ts";

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

test("the pictures in public/ need no Host check: the image optimizer asks for them with none", () => {
  for (const path of ["/swirl.jpg", "/kako-mark.png"]) {
    assert.equal(isPublicPicture(path), true, path);
  }
});

test("the list is exactly the pictures in public/", () => {
  const folder = new URL("../../public/", import.meta.url);
  const pictures = readdirSync(folder)
    .filter((name) => /\.(?:png|jpe?g|webp|avif|gif|svg|ico)$/i.test(name))
    .map((name) => `/${name}`)
    .sort();
  assert.deepEqual([...PUBLIC_PICTURES].sort(), pictures);
});

test("pages, routes, /api and anything else keep the Host check", () => {
  for (const path of [
    "/",
    "/sessions/abc",
    "/sessions/abc.png",
    "/plans/1.png",
    "/docs/rule.svg",
    "/api/v1/household",
    "/api/v1/x.png",
    "/API/v1/sessions/x.png",
    "/Api/v1/swirl.jpg",
    "/api/v1/swirl.jpg",
    "/_next/image",
    "/SWIRL.JPG",
    "/swirl.jpg/",
    "/brand/kako-mark.png",
    "/../api/v1/x.png",
    "/%2e%2e/api/v1/x.png",
    "/swirl.jpg.html",
    "/swirl",
    "//evil.example/x.png",
  ]) {
    assert.equal(isPublicPicture(path), false, path);
  }
});
