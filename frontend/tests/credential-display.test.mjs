import assert from "node:assert/strict";
import test from "node:test";

import {
  loadCredentialDisplay,
  maskCredentialForDisplay,
} from "../src/lib/credentialDisplay.js";

test("stored secret masks never become editable credential values", () => {
  const loaded = loadCredentialDisplay(
    ["alpaca_api_key", "tradier_market_api_key", "tradier_live_account_id"],
    ["alpaca_api_key", "tradier_market_api_key"],
    {
      alpaca_api_key: "PK12…3456",
      tradier_market_api_key: "abcd…wxyz",
      tradier_live_account_id: "6YB84763",
    },
  );

  assert.deepEqual(loaded.values, {
    alpaca_api_key: "",
    tradier_market_api_key: "",
    tradier_live_account_id: "6YB84763",
  });
  assert.deepEqual(loaded.savedMasks, {
    alpaca_api_key: "PK12…3456",
    tradier_market_api_key: "abcd…wxyz",
  });
});

test("newly saved secrets are represented only by a display mask", () => {
  assert.equal(maskCredentialForDisplay("abcdefghijkl"), "abcd…ijkl");
  assert.equal(maskCredentialForDisplay("short"), "set");
  assert.equal(maskCredentialForDisplay(""), "");
});
