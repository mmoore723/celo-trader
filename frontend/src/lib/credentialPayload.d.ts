export interface SetupCredentials {
  alpaca_api_key: string;
  alpaca_secret_key: string;
  tradier_market_api_key: string;
}

export function buildCredentialStepPayload(
  step: number,
  credentials: SetupCredentials,
): Record<string, string>;
