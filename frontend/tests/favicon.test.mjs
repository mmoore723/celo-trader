import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the browser tab uses the cache-busted green Celo C favicon", () => {
  assert.match(index, /rel="icon" type="image\/svg\+xml" href="\/favicon\.svg\?v=celo-green-c-4"/);
  assert.match(index, /rel="shortcut icon" type="image\/svg\+xml" href="\/favicon\.svg\?v=celo-green-c-4"/);
  assert.match(index, /rel="apple-touch-icon" href="\/logo\.png\?v=celo-green-c-4"/);
});
