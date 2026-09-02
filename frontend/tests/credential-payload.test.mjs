import assert from "node:assert/strict";
import test from "node:test";

import { buildCredentialStepPayload } from "../src/lib/credentialPayload.js";

const credentials = {
  alpaca_api_key: " paper-key ",
  alpaca_secret_key: " paper-secret ",
  tradier_market_api_key: " live-market-token ",
};

test("Alpaca onboarding sends the server credential field names", () => {
  assert.deepEqual(buildCredentialStepPayload(0, credentials), {
    alpaca_api_key: "paper-key",
    alpaca_secret_key: "paper-secret",
  });
});

test("Tradier onboarding saves the production token used for current prices", () => {
  assert.deepEqual(buildCredentialStepPayload(1, credentials), {
    tradier_market_api_key: "live-market-token",
  });
});

test("completed onboarding sends no credential mutation", () => {
  assert.deepEqual(buildCredentialStepPayload(2, credentials), {});
});
