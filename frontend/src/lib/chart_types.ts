/**
 * chart_types.ts — Shared overlay types for TradingChart simulation + replay modes.
 *
 * SimulationOverlay  — pre-trade projection (used from DailyBrief premarket panel)
 * ReplayTrade        — historical trade replay (used from Journal trade drawer)
 */

/** Pre-trade simulation: show where bot would enter + projected targets/stop on the chart */
export interface SimulationOverlay {
  direction: "calls" | "puts";
  grade: string;          // A+, A, B, C, Watch
  orbHigh: number;        // previous session high / ORB reference top
  orbLow: number;         // previous session low  / ORB reference bottom
  entryTrigger: number;   // stock price where bot would trigger (orbHigh for calls, orbLow for puts)
  stage1Px: number;       // projected stock price at Stage 1 target (+ATR*0.5 from entry)
  stopPx: number;         // projected stock price at stop       (-ATR*0.3 from entry)
  currentPx: number;      // current pre-market price (marks where stock is now)
  atr: number;            // ATR used for projections
}

/** Historical trade replay: annotate entry / exit / MFE / MAE on a past day's chart */
export interface ReplayTrade {
  entry_time: string;
  exit_time?: string;
  entry_option_px: number;   // option price at entry (for R:R display)
  exit_option_px?: number;   // option price at exit
  peak_option_px?: number;   // MFE (highest option price)
  mae_option_px?: number;    // MAE (lowest option price)
  direction: "long" | "short";
  exit_reason?: string;
  pnl?: number;
  contracts?: number;
  // Higher-timeframe trend agreement at entry — see Trade.mtf_bias in api.ts.
  mtfBias?: Record<string, "with" | "against" | "neutral">;
}
