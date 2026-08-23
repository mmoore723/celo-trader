export type StrategyExecutionStateInput = {
  account_mode: "paper" | "live";
  execution_enabled: boolean;
  live_eligible: boolean;
};

export type StrategyExecutionState = {
  badge: string;
  tone: "green" | "yellow" | "neutral";
  detail: string;
};

export function strategyExecutionState(
  strategy: StrategyExecutionStateInput,
  switchEnabled: boolean,
): StrategyExecutionState;
