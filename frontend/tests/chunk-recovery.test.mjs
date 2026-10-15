import assert from "node:assert/strict";
import test from "node:test";
import { isChunkLoadError, recoverPage } from "../src/lib/chunkRecovery.js";

test("missing LiveTrading chunk reloads rather than retrying cached rejected import", () => {
  let reloads = 0, resets = 0;
  recoverPage(new Error("Failed to fetch dynamically imported module: https://celotrader.com/assets/LiveTrading-BwGzuujP.js"), () => reloads++, () => resets++);
  assert.equal(reloads, 1);
  assert.equal(resets, 0);
});
test("ordinary render failures retain normal retry", () => {
  let reloads = 0, resets = 0;
  recoverPage(new Error("Undefined field"), () => reloads++, () => resets++);
  assert.equal(reloads, 0);
  assert.equal(resets, 1);
});
test("Safari and preload errors support recovery", () => {
  assert.equal(isChunkLoadError(new Error("Importing a module script failed.")), true);
  assert.equal(isChunkLoadError(new Error("Unable to preload CSS for /assets/old.css")), true);
  assert.equal(isChunkLoadError(null), false);
});
