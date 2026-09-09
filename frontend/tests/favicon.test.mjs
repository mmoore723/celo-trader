import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");

test("the browser tab uses the branded Celo logo instead of the retired svg", () => {
  assert.match(index, /rel="icon" type="image\/png" href="\/logo\.png\?v=celo-logo-3"/);
  assert.match(index, /rel="shortcut icon" type="image\/png" href="\/logo\.png\?v=celo-logo-3"/);
  assert.doesNotMatch(index, /href="\/favicon\.svg/);
});
