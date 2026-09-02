export function buildCredentialStepPayload(step, credentials) {
  if (step === 0) {
    return {
      alpaca_api_key: String(credentials.alpaca_api_key ?? "").trim(),
      alpaca_secret_key: String(credentials.alpaca_secret_key ?? "").trim(),
    };
  }
  if (step === 1) {
    return {
      tradier_market_api_key: String(credentials.tradier_market_api_key ?? "").trim(),
    };
  }
  return {};
}
