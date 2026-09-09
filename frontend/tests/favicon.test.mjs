import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the browser tab uses a uniquely named branded Celo favicon", () => {
  assert.match(index, /rel="icon" type="image\/svg\+xml" sizes="any" href="\/celo-favicon-20260909\.svg"/);
  assert.match(index, /rel="shortcut icon" type="image\/svg\+xml" href="\/celo-favicon-20260909\.svg"/);
  assert.match(index, /rel="apple-touch-icon" href="\/logo\.png\?v=celo-brand-20260909"/);
});
