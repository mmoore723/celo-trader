/**
 * Describe what the current user's strategy switch can do in the account mode
 * shown by Settings. Live-promotion state is intentionally secondary: a
 * paper-enabled strategy should not be mislabeled as observation-only merely
 * because it has not been promoted for live-money orders.
 */
export function strategyExecutionState(strategy, switchEnabled) {
  if (!switchEnabled) {
    return {
      badge: strategy.account_mode === "paper" ? "PAPER READY · OFF" : "OBSERVATION OFF",
      tone: "neutral",
      detail: "evaluation switch is off",
    };
  }

  if (strategy.execution_enabled) {
    return {
      badge: strategy.account_mode === "paper" ? "PAPER EXECUTION ON" : "LIVE EXECUTION ON",
      tone: "green",
      detail: `can execute in this ${strategy.account_mode} account`,
    };
  }

  if (strategy.account_mode === "live" && !strategy.live_eligible) {
    return {
      badge: "SHADOW ONLY IN LIVE",
      tone: "yellow",
      detail: "evaluating setups with zero live-order authority",
    };
  }

  return {
    badge: "EXECUTION BLOCKED",
    tone: "yellow",
    detail: "enabled, but an integrity or eligibility gate is blocking orders",
  };
}
