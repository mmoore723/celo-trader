import type { BrokerConnectionHealth, BrokerConnectionRow } from "./api";
export function connectionHealthView(
  health: BrokerConnectionHealth | undefined,
  options?: { failed?: boolean; now?: number },
): { verified: boolean; hasIssue: boolean; checkedAt: string | null; connections: BrokerConnectionRow[] };
export function needsTradierSandbox(provider: string, paper: boolean): boolean;
