/**
 * lib/api.ts — Typed API client for all FastAPI endpoints.
 */

import type { OptionChartData } from "./optionChart";
const BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",   // send session cookie with every API call
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) {
      // Session expired mid-session — fire an event so AuthContext can
      // redirect to Login without requiring a full page reload.
      window.dispatchEvent(new CustomEvent("celo:session-expired"));
    }
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ── Types (matching api/models.py) ─────────────────────────────────────────

export interface BotStatus {
  running: boolean;
  mode: string;
  ticker: string | null;
  broker_connected: boolean;
  account_balance: number;
  day_start_balance: number;   // Broker prior-close equity, or first persisted daily balance
  session_pnl: number;
  options_buying_power: number;
  last_update: string | null;
  network_ok: boolean;
  last_strategy_id: string | null;
  current_stop_pct: number | null;
  last_signal: string | null;
  ghost_position_detected: boolean;
  // 2026-07-31: see broker_health.py — non-empty when a broker (Tradier/Alpaca)
  // has failed enough calls recently that trading is effectively blind.
  broker_alerts?: { broker: string; error_count: number; since: number; last_error: string }[];
  opportunity_window?: {
    ticker?: string; strategy_id?: string; direction?: string;
    confidence?: number; started_at?: string; expires_at?: string;
  };
}

export interface BrokerConnectionRow {
  id: string;
  label: string;
  purpose: string;
  status: "connected" | "error" | "missing" | "not_used";
  detail: string;
  required: boolean;
}

export interface BrokerConnectionHealth {
  ready: boolean;
  selected_broker: "alpaca" | "tradier";
  mode: "paper" | "live";
  checked_at: string;
  connections: BrokerConnectionRow[];
}

export interface StrategyScorecardRow {
  strategy_id: string; closed_trades: number; wins: number; pnl: number;
  blocked_signals: number; entered_signals: number; block_reasons: Record<string, number>;
  win_rate: number | null; expectancy: number | null;
  sample_status: "review_ready" | "collecting_data";
}
export interface StrategyScorecard {
  days: number; minimum_review_trades: number; strategies: StrategyScorecardRow[];
  opportunity_strategies: StrategyScorecardRow[];
}
export interface CandidateScorecardRow {
  strategy_id: string; raw_candidates: number; entered: number;
  blocked: number; pending: number; observed_only: number; measured: number; correct: number;
  directional_win_rate: number | null; avg_directional_move_pct: number | null;
  block_reasons: Record<string, number>;
  outcome_evidence: Record<"observed_only" | "blocked" | "entered", CandidateOutcomeEvidence>;
}
export interface CandidateOutcomeEvidence {
  candidates: number; measured: number; correct: number;
  directional_win_rate: number | null; avg_directional_move_pct: number | null;
}
export interface CandidateScorecard {
  days: number; account_scoped: boolean; note: string;
  total_candidates: number; measured_candidates: number; next_outcome_at: string | null;
  strategies: CandidateScorecardRow[];
}
export interface ResearchContractTest {
  policy: string;
  label: string;
  profile_version: string;
  status: StrategyTickerResearchPair["status"];
  explanation: string;
  option_results: number;
  option_result_days: number;
  wins: number;
  win_rate_pct: number | null;
  profit_factor: number | "infinite" | null;
  net_one_contract_pnl: number;
  mistimed_quotes_ignored: number;
  older_profit_factor: number | "infinite" | null;
  newer_profit_factor: number | "infinite" | null;
  comparison_split_date?: string | null;
}
export interface StrategyTickerResearchPair {
  ticker: string;
  status: "working" | "promising" | "losing_so_far" | "needs_tuning" | "not_working" | "collecting" | "no_setups";
  explanation: string;
  market_days: number;
  setups: number;
  raw_observations: number;
  rule_rejected: number;
  rule_unscored: number;
  previous_version_rows: number;
  stale_or_replayed: number;
  option_results: number;
  option_result_days: number;
  wins: number;
  win_rate_pct: number | null;
  profit_factor: number | "infinite" | null;
  net_one_contract_pnl: number;
  direction_results: number;
  direction_accuracy: number | null;
  quote_coverage_pct: number | null;
  mistimed_quotes_ignored: number;
  legacy_option_profiles_ignored: number;
  older_profit_factor: number | "infinite" | null;
  newer_profit_factor: number | "infinite" | null;
  comparison_split_date?: string | null;
  diagnosis: "ready" | "more_data" | "no_setups" | "price_data" | "unstable" | "early_loss" | "entry" | "exit" | "contract_exit";
  next_action: string;
  exit_comparison: {
    minutes: number;
    option_results: number;
    wins: number;
    win_rate_pct: number | null;
    profit_factor: number | "infinite" | null;
    net_one_contract_pnl: number;
    mistimed_quotes_ignored: number;
  }[];
  contract_tests: ResearchContractTest[];
  leading_contract_test: ResearchContractTest | null;
  research_contract_profile: string | null;
  tradable: boolean;
}
export interface StrategyResearchMatrix {
  days: number;
  target_profit_factor: number;
  collection_started_on: string | null;
  collected_market_days: number;
  recommendation_policy: {
    minimum_market_days: number;
    minimum_result_days: number;
    target_profit_factor: number;
  };
  cost_model: string;
  account_scoped: boolean;
  ticker_count: number;
  strategy_count: number;
  strategies: {
    strategy_id: string;
    display_name: string;
    version: string;
    backtest: {
      profit_factor?: number | "infinite" | "no fills";
      trades?: number;
      scope?: string;
      note?: string;
      meets_target?: boolean;
      historical_test_through?: string;
      forward_evidence_start?: string;
    };
    current_evidence: {
      profit_factor: number | "infinite" | null;
      option_results: number;
      option_result_days: number;
      net_one_contract_pnl: number;
    };
    research_enabled: boolean;
    trading_tickers: string[];
    exit_minutes: number;
    pairs: StrategyTickerResearchPair[];
  }[];
}
export interface DailyEvidenceScorecard {
  date: string; mode: "paper" | "live"; account_scoped: boolean;
  session_result: { grade: string; label: string; net_pnl: number; basis: string };
  trading: {
    closed_trades: number; wins: number; losses: number; win_rate_pct: number | null;
    profit_factor: number | "infinite" | null; avg_win: number | null;
    avg_loss: number | null; largest_loss: number | null;
  };
  decisions: {
    candidates: number; independent_candidates: number;
    entered: number; blocked: number; measured: number;
    directional_accuracy_pct: number | null;
    research_candidates: number; research_measured: number;
    research_directional_accuracy_pct: number | null;
    missed_executable_moves: Record<string, {
      measured: number; profitable: number; avg_executable_return_pct: number | null;
      estimated_pnl_dollars?: number | null; contracts?: number; basis?: string;
    }>;
  };
  execution: {
    entry_attempts: number; entry_filled: number; entry_fill_rate_pct: number | null;
    exit_attempts: number; exit_filled: number; exit_fill_rate_pct: number | null;
    attempts_with_issues: number;
    quote_to_fill: {
      paired_fills: number;
      paired_contracts: number;
      signed_adverse_slippage_dollars: number | null;
      average_signed_slippage_per_contract: number | null;
      interpretation: string;
    };
    tradier_quote_replay: {
      measured_trades: number;
      exact_exit_quotes: number;
      legacy_nearby_marks: number;
      recorded_paper_pnl: number | null;
      quote_pnl_before_fees: number | null;
      quote_pnl_after_fees: number | null;
      quote_profit_factor_after_fees: number | null;
      paper_minus_quote_before_fees: number | null;
      gross_profit_after_fees: number | null;
      gross_loss_after_fees: number | null;
      excluded: Record<string, number>;
      basis: string;
    };
  };
  replay: {
    passed: boolean; chronological: boolean; coverage_pct: number;
    checks: { name: string; expected: number; proven: number; coverage_pct: number }[];
    issues: string[];
  };
  observations: string[];
  launch_readiness: { status: string; note: string };
}
export interface PaperResearchScorecard {
  study_id: string; observations: number; closed: number; unavailable: number;
  quote_measured: number; option_win_rate_pct: number | null;
  avg_underlying_move_pct: number | null; avg_executable_return_pct: number | null;
  note: string;
}
export interface V2OrbPaperScorecard {
  strategy_id: string; broker_account_id: string | null; account_scoped: boolean;
  entered: number; open_trades: number; closed_trades: number; wins: number;
  win_rate_pct: number | null; pnl: number; average_return_pct: number | null;
  study_matched_exits: number; nonmatching_exits: number;
  minimum_review_trades: number; sample_status: "collecting_data" | "review_ready";
  note: string;
}
export interface PaidResearchEvidence {
  study_id: string; label: string; status: "paper_validation_next";
  ticker: string; strategy_id: string; data_scope: string; execution_model: string;
  rejected_comparison: { label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number; interpretation: string };
  rejected_vwap_strategy: {
    label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number;
    holdout_measured_signals: number; holdout_win_rate_pct: number; holdout_average_return_pct: number;
    interpretation: string;
  };
  baseline: { label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number };
  unseen_holdout: { label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number };
  walkforward: {
    label: string;
    baseline: { measured_signals: number; average_return_pct: number };
    best_past_variant: { measured_signals: number; average_return_pct: number };
  };
  uncertainty: { label: string; low_pct: number; high_pct: number; interpretation: string };
  paper_pilot: { contract_rule: string; exit_rule: string; why: string };
  exit_comparison: {
    label: string;
    fixed_90m: { average_return_pct: number; measured_signals: number };
    vwap_loss: { average_return_pct: number; measured_signals: number };
    ema9_loss: { average_return_pct: number; measured_signals: number };
    conclusion: string;
  };
  what_changed: string; next_step: string; caveat: string;
}
export interface PaidTrendResearchProgress {
  available: boolean; study_id: string; label: string; note: string;
  ticker?: string; strategy?: string; complete?: boolean;
  status?: "testing_exit_clock" | "testing_new_dates" | "review_pending";
  processed_days?: number; total_days?: number; progress_pct?: number;
  provisional_exit_minutes?: number | null; holdout_signals_seen?: number;
  decision?: string;
}

export interface Trade {
  id: number;
  contract_symbol?: string;
  strike?: number;
  expiry?: string;
  ticker: string;
  direction: string;
  option_type?: string;
  strategy_id?: string;
  entry_price: number;
  exit_price?: number;
  stop_price?: number;
  target_price?: number;
  trail_price?: number;
  // MFE / MAE — populated once the trade closes (position_manager saves at close)
  peak_price?: number;            // highest option price seen during trade
  mae_price?: number;             // lowest  option price seen during trade
  mfe_pct?: number;               // (peak - entry) / entry * 100
  mae_pct?: number;               // (mae  - entry) / entry * 100  (negative = adverse)
  exit_efficiency_pct?: number;   // (exit - entry) / (peak - entry) * 100
  contracts: number;
  pnl?: number;
  status: string;
  entry_time?: string;
  exit_time?: string;
  exit_reason?: string;
  stage1_done?: boolean;
  mode?: string;
  recap?: string;           // auto-generated post-trade recap narrative
  // Bot's own chart annotations (FVG zones, BOS/TREND_CONT levels, signal
  // markers) captured at entry + exit time — same shape as ChartAnnotation
  // below, but persisted per-trade so Journal replay works for any past day
  // (the live /api/bot/annotations feed is ephemeral and gets overwritten).
  annotations?: ChartAnnotation[];
  // Higher-timeframe trend agreement at entry — "with" | "against" | "neutral"
  // per timeframe, saved best-effort after the trade was recorded.
  mtf_bias?: Record<string, "with" | "against" | "neutral">;
}

// ── Analytics ──────────────────────────────────────────────────────────────

export interface StrategyRow {
  strategy_id: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  avg_mfe_pct: number;
  current_version?: string | null;
  current_version_trades?: number;
  current_version_wins?: number;
  current_version_losses?: number;
  current_version_total_pnl?: number;
  current_version_profit_factor?: number;
  prior_or_unversioned_trades?: number;
}

export interface HourRow {
  hour: number;
  label: string;
  trades: number;
  wins: number;
  win_rate: number;
  avg_pnl: number;
}

export interface TickerRow {
  ticker: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
}

export interface ExitReasonRow {
  reason: string;
  trades: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface TradeAnalytics {
  by_strategy: StrategyRow[];
  by_hour: HourRow[];
  by_ticker: TickerRow[];
  by_exit_reason: ExitReasonRow[];
  avg_mfe_pct: number;
  avg_exit_pct: number;
  avg_exit_efficiency_pct: number;
}

// ── Options chain ──────────────────────────────────────────────────────────

export interface OptionsChainRow {
  strike: number;
  call_bid?: number; call_ask?: number; call_mid?: number;
  call_delta?: number; call_iv?: number; call_oi?: number;
  put_bid?: number; put_ask?: number; put_mid?: number;
  put_delta?: number; put_iv?: number; put_oi?: number;
}

export interface TradeListResponse {
  trades: Trade[];
  total: number;
  total_pnl: number;
  win_rate: number;
}

// ── Strategy Health (built-in audit — replaces one-off diag scripts) ───────

export interface StrategyFunnelRow {
  raw_signals: number;
  router_survivors: number;
  worked_raw: number;
  worked_survivors: number;
  actual_trades: number;
  actual_wins: number;
  actual_pnl: number;
}

// ── AI reasoning replay log ────────────────────────────────────────────────
// Full prompt/response trail for every AI call (narration + decision
// support), win or lose, error or not. Added 2026-07-20 so the user can
// audit exactly what was sent to and received from the model — verifying
// against hallucination/prompt drift, not trusting a summary.
export interface AiReasoningEntry {
  id: number;
  ts: string;
  event_type: "entry_narration" | "exit_narration" | "entry_veto"
    | "daily_audit_summary" | "weekly_audit_summary" | string;
  ticker: string;
  trade_id: number | null;
  feature_snapshot_json: string;   // JSON-encoded — parse for the exact input dict
  prompt: string;                  // full system+user prompt text, verbatim
  response_text: string | null;    // raw model output, verbatim (null on failure)
  latency_ms: number | null;
  model: string | null;
  error: string | null;
  applied: number;   // 1 if a veto/resize was actually acted on (phase 2 only)
}

// signal_journal — every strategy signal's final outcome, entered or
// blocked-with-reason. Added 2026-07-24 for the Thinking panel's summary
// bar / filterable row list / 7-day trend strip. See signal_journal.py.
export interface SignalJournalEntry {
  id: number;
  ts: string;
  ticker: string;
  strategy_id: string;
  direction: string;              // "bullish" | "bearish"
  confidence: number;             // 0.0-1.0
  outcome: "entered" | "blocked";
  reason_code: string | null;     // null when outcome="entered"
  reason_detail: string | null;
}

export interface SignalJournalSummary {
  total: number;
  entered: number;
  by_reason: Record<string, number>;   // reason_code -> count
}

export interface SignalJournalTrendPoint { date: string; count: number }

// Scanner Opportunities is intentionally distinct from Trade Journal.  It
// begins with every signal the scanner evaluated, then shows a contract/size
// only if the entry path genuinely reached those decisions.
export interface ScannerOpportunityContract {
  symbol?: string | null; strike?: number | null; expiry?: string | null;
  bid?: number | null; ask?: number | null; spread?: number | null;
  volume?: number | null; open_interest?: number | null;
  selection_model?: string | null;
}
export interface ScannerOpportunityContractRecipe {
  option_type?: string; strike_rule?: string; premium_rule?: string; expiration_rule?: string;
  spread_rule?: string; liquidity_rule?: string; maximum_cost?: number; selection_model?: string;
  recipe_source?: "recorded" | "default_profile" | string;
}
export interface ScannerOpportunityContractSelection {
  status?: "selected" | "not_selected" | string; reason?: string;
  cheapest_cost?: number | null; cheapest_symbol?: string | null;
  illiquid_cost?: number | null; illiquid_symbol?: string | null; liquidity_detail?: string | null;
  selected_dte?: number | null; selected_spread_pct?: number | null;
}
export interface ScannerOpportunityContractPreview extends ScannerOpportunityContract {
  status?: "selected" | "not_selected" | string; observed_at?: string;
  underlying_price?: number | null; reason?: string;
  cheapest_cost?: number | null; cheapest_symbol?: string | null;
  illiquid_cost?: number | null; illiquid_symbol?: string | null; liquidity_detail?: string | null;
  planned_entry_price?: number | null; planned_contracts?: number | null;
  working_limit?: number | null; step_limit?: number | null;
  maximum_entry_price?: number | null;
  estimated_position_cost?: number | null;
}
export interface ScannerOpportunityQuoteMark {
  observation_kind: "entry" | "mark_30m" | "mark_60m" | "mark_90m" | "mark_120m" | string;
  observed_at: string; contract_symbol: string;
  bid?: number | null; ask?: number | null; mid?: number | null; last?: number | null;
  executable_return_pct?: number | null; source?: string;
}
export interface ScannerOpportunityTrade {
  id: number; contract_symbol?: string | null; option_type?: string | null;
  strike?: number | null; expiry?: string | null; contracts?: number | null;
  entry_price?: number | null; exit_price?: number | null; status?: string | null;
  stop_price?: number | null; target_price?: number | null;
  entry_time?: string | null; exit_time?: string | null; exit_reason?: string | null;
  pnl?: number | null;
}
export interface ScannerOpportunityOrderIntent {
  intent_id?: string; status?: string; created_at?: string; expires_at?: string;
  candidate_id?: string | null; ticker?: string; strategy_id?: string; direction?: string;
  option_type?: string; contract_symbol?: string; strike?: number | null; expiry?: string | null;
  quote_bid?: number | null; quote_ask?: number | null; working_limit?: number | null;
  step_limit?: number | null; maximum_entry_price?: number | null; quantity?: number | null;
  estimated_notional?: number | null; rr_ratio?: number | null;
  broker_order_id?: string | null; execution_attempt_id?: string | null;
  confirmed_fill_price?: number | null; trade_id?: number | null;
}
export interface ScannerOpportunity {
  id: string; source: "candidate" | "journal_only"; observed_at: string;
  ticker: string; strategy_id: string; direction: "bullish" | "bearish" | string;
  confidence: number; tier: "main" | "opportunity" | string; trigger_bar?: string | null;
  outcome: "pending" | "blocked" | "observed_only" | "entered" | string;
  reason_code?: string | null; reason_detail?: string | null;
  entry_plan: { trigger?: string; underlying_price?: number; estimated_entry_price?: number };
  contract: ScannerOpportunityContract;
  contract_preview?: ScannerOpportunityContractPreview;
  contract_recipe?: ScannerOpportunityContractRecipe;
  contract_selection?: ScannerOpportunityContractSelection;
  planned_quantity?: number | null;
  exit_plan: { strategy_id?: string; summary?: string };
  order_intent?: ScannerOpportunityOrderIntent;
  plan_status: "contract_selected" | "contract_preview" | "not_priced" | "observation_only" | string;
  option_quote_timeline?: ScannerOpportunityQuoteMark[];
  option_type?: "call" | "put" | string | null;
  setup_details?: Record<string, string | number | boolean>;
  underlying_entry_price?: number | null; underlying_exit_price?: number | null;
  directional_move_pct?: number | null; direction_correct?: number | null;
  outcome_observed_at?: string | null; trade?: ScannerOpportunityTrade | null;
  lifecycle?: "watching" | "pricing" | "ready" | "stopped" | "entered" | "research" | string;
  episode_id?: string; episode_occurrence?: number; episode_size?: number;
}
export interface ScannerOpportunitiesResponse {
  date: string; account_scoped: boolean; available_dates: string[];
  summary: {
    setups: number; raw_detections: number; actionable: number; entered: number;
    stopped: number; research: number; watching: number; pricing: number; ready: number;
    [key: string]: number;
  };
  note: string; entries: ScannerOpportunity[];
}
export interface GateCalibrationRow {
  strategy_id: string; gate: "ai_decision_veto" | "macro_vwap_veto" | string;
  raw_decisions: number; independent_episodes: number; delayed_then_allowed: number;
  enforced: boolean;
  vetoes: number; measured: number; avoided_losers: number; rejected_winners: number;
  option_measured: number; trading_days: number; avoided_loser_rate_pct?: number | null;
  rejected_winner_rate_pct?: number | null; avg_rejected_option_return_pct?: number | null;
  status: "collecting_option_outcomes" | "collecting_action_balance" | "collecting_holdout_days" | "validated_candidate" | "failed_chronological_validation" | "descriptive_only" | string;
  allowed: { decisions: number; measured: number; winners: number; losers: number; option_measured: number; win_rate_pct?: number | null };
  minimum_evidence: Record<string, number>;
  validation?: {
    status: string; recommended_for_enforcement: boolean; option_episodes: number;
    trading_days: number; veto_episodes: number; approval_episodes: number;
    minimum_evidence: Record<string, number>;
    training?: GatePeriodMetrics | null; holdout?: GatePeriodMetrics | null;
    checks?: Record<string, boolean>;
  } | null;
}
export interface GatePeriodMetrics {
  episodes: number; days: number; baseline_avg_return_pct?: number | null;
  ai_policy_avg_return_pct?: number | null; incremental_avg_return_pct?: number | null;
  baseline_profit_factor?: number | "infinite" | null;
  ai_policy_profit_factor?: number | "infinite" | null;
}
export interface GateCalibrationScorecard {
  days: number; account_scoped: boolean; policy: string; rows: GateCalibrationRow[];
}

export interface WatchingContract {
  symbol: string | null;
  strike: number | null;
  expiry: string | null;
  bid: number | null;
  ask: number | null;
}

export interface WatchingSignal {
  ticker: string;
  strategy: string;              // reviewed V2 strategy ID
  direction: "bullish" | "bearish" | null;
  option_type: "call" | "put" | null;
  phase: "breakout_seen" | "retesting" | "expired";
  phase_label: string;           // "1 of 3 — breakout seen" | "2 of 3 — retesting"
  retest_level: number | null;
  current_price: number | null;
  breakout_time: string | null;
  retest_time: string | null;
  contract: WatchingContract | null;
}

export interface TickerBoardRow {
  ticker: string;
  status: "trading" | "watching" | "blocked";
  strategy: string | null;
  direction: string | null;
  detail: string;                 // human line: "entered 9:41 AM" | "2 of 3 — retesting" | reason text
  time: string | null;
  reason_code?: string | null;    // only present when status === "blocked" — feeds buildGateChips()
  retest_level: number | null;    // only meaningful when status === "watching"
  contract: {
    symbol: string | null;
    strike: number | null;
    expiry: string | null;
    bid?: number | null;          // present on watching rows only
    ask?: number | null;
  } | null;
  entry_price: number | null;
  current_price: number | null;
  pnl: number | null;
}

export interface StrategyHealthAggregate {
  date: string;
  tickers_scanned: string[];
  per_strategy: Record<string, StrategyFunnelRow>;
}

export interface StrategyHealthAudit {
  available: boolean;
  audit_date?: string;
  created_at?: string;
  tickers?: string;
  aggregate?: StrategyHealthAggregate;
  rule_summary?: string;
  ai_summary?: string | null;
}

export interface StrategyHealthHistoryRow {
  audit_date: string;
  created_at: string;
  tickers: string;
  rule_summary: string;
  ai_summary: string | null;
}

// ── Weekly strategy review (added 2026-07-20) ──────────────────────────────
// Same page as the daily audit, different time horizon — rolls up the
// trailing week's daily audits + real closed trades (win rate, exit-reason
// mix, realized R:R) into one view, with an AI layer specifically asked for
// a concrete, testable recommendation rather than a daily summary.
export interface StrategyRiskMathRow {
  n: number;
  win_rate_pct: number;
  avg_pnl: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  realized_rr: number | null;
  exit_reasons: Record<string, number>;
}

export interface WeeklyAggregate {
  week_label: string;
  window_days: number;
  daily_audits_included: string[];
  per_strategy_funnel: Record<string, StrategyFunnelRow>;
  per_strategy_risk_math: Record<string, StrategyRiskMathRow>;
}

export interface WeeklyReview {
  available: boolean;
  audit_date?: string;   // ISO year-week label, e.g. "2026-W29"
  created_at?: string;
  aggregate?: WeeklyAggregate;
  rule_summary?: string;
  ai_summary?: string | null;
}

// ── Reconciliation types ──────────────────────────────────────────────────────
export interface AlpacaOrder {
  order_id: string;
  symbol: string;
  side: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  status: string;
  submitted_at: string | null;
  filled_at: string | null;
}

export interface ReconcileRow {
  trade_id: number | null;
  ticker: string | null;
  strategy_id: string | null;
  contracts: number | null;
  contract_symbol: string | null;
  status: "open" | "closed" | null;
  bot_entry: number | null;
  bot_exit: number | null;
  bot_pnl: number | null;
  entry_time: string | null;
  exit_time: string | null;
  alpaca_entry: number | null;
  alpaca_exit: number | null;
  alpaca_pnl: number | null;
  pnl_gap: number | null;
  has_gap: boolean;
}

export interface ReconcileResponse {
  date: string;
  broker_provider: "alpaca" | "tradier";
  alpaca_equity: number | null;
  day_start_balance: number | null;
  bot_session_pnl: number;
  alpaca_session_pnl: number | null;
  equity_gap: number | null;
  trades: ReconcileRow[];
  unmatched_alpaca_orders: AlpacaOrder[];
}

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
  vwap_upper1?: number;
  vwap_lower1?: number;
  vwap_upper2?: number;
  vwap_lower2?: number;
  rvol?: number;
  atr?: number;
}

export type LearningExampleCategory =
  | "clean_win"
  | "valid_loss"
  | "false_breakout_or_chop"
  | "rejected_missing_condition"
  | "ambiguous_no_trade";

export interface LearningStrategyProgress {
  strategy_id: string;
  display_name: string;
  version: string;
  tickers: string[];
  target: number;
  curated_examples: number;
  categories: Record<LearningExampleCategory, number>;
  category_targets: Record<LearningExampleCategory, number>;
}

export interface LearningCatalogResponse {
  strategies: LearningStrategyProgress[];
  grounding: string;
  order_authority: false;
}

export interface LearningExample {
  example_id: string;
  strategy_id: string;
  strategy_version: string;
  ticker: string;
  observed_at: string;
  trigger_bar?: string | null;
  direction: string;
  category: LearningExampleCategory;
  outcome: string;
  gate_reason?: string | null;
  gate_detail?: string | null;
  directional_move_pct?: number | null;
  direction_correct?: number | null;
  outcome_observed_at?: string | null;
  bars: Bar[];
  decision_bar_index: number;
  coach: { summary: string; prompt: string };
  provenance: string;
  episode_size: number;
  practice_eligible: boolean;
}

export interface LearningExamplesResponse {
  strategy_id: string;
  examples: LearningExample[];
  count: number;
}
export interface LearningPracticeStart {
  session_id: string; expires_at: string;
  example: Pick<LearningExample, "example_id" | "strategy_id" | "strategy_version" | "ticker" | "observed_at" | "bars" | "decision_bar_index"> & { prompt: string };
}
export interface LearningPracticeResult { correct: boolean; answer: "call" | "put" | "wait" | "reject"; example: LearningExample }
export interface LearningCoachAnswer { answer: string; citations: { id: string; source: string }[]; order_authority: false; external_data_transfer: false }
export interface LearningRankerStatus { status: "collecting" | "shadow_active" | "trained_not_qualified"; usable_episodes: number; required?: number; remaining?: number; model_id?: string; order_authority: false }

export interface OpeningRange {
  high?: number;
  low?: number;
  open?: number;
  close?: number;
  volume?: number;
  /** Trading-session date/time represented by this range. */
  time?: string;
  /** Number of completed five-minute bars used to build the range. */
  bars?: number;
}

export interface Quote {
  ticker: string;
  price: number;
  change_pct: number;
  volume: number;
}

export interface ScannerResult {
  ticker: string;
  rvol: number;
  price: number;
  atr: number;
  change_pct: number;
  rank: number;
}

export interface PremarketTicker {
  ticker: string;
  price: number;
  prev_close: number;
  prev_high: number;
  prev_low: number;
  gap_pct: number;
  atr: number;
  atr_pct: number;
  avg_vol_20d: number;
  daily_vol: number;
  rvol: number;
  implied_move_pct: number;
  grade: string;                // "A+" | "A" | "B" | "C" | "Watch"
  direction: string;            // "calls" | "puts" | "neutral"
  fit_score: number;
  readiness_score: number;
  tradeable_today: boolean;
  best_strategy: { strategy_id: string; name: string; fit_score: number; readiness_score: number; direction: string; can_trade: boolean; reason: string } | null;
  strategy_matches: { strategy_id: string; name: string; fit_score: number; readiness_score: number; direction: string; can_trade: boolean; reason: string }[];
  timeframes: { label: string; bias: "up" | "down" | "flat" | "unavailable"; change_pct: number | null }[];
  entry_note: string;
  stop_note: string;
  target_note: string;
  key_levels: { label: string; price: number; type: string }[];
  setup_notes: string;
  is_pinned: boolean;
  rank: number;
}

export interface AppSettings {
  broker_provider?: "alpaca" | "tradier";
  paper_trading?: boolean;   // true = paper (default), false = live; only toggled via Settings
  risk_pct: number;
  risk_auto?: boolean;       // true = use the balance-based tier, not a manual override
  growth_mode: boolean;
  flip_trading_enabled: boolean;
  max_concurrent_positions: number;
  rr_ratio_mode: string;
  watchlist: string[];
  validated_strategy_ids?: string[]; // server-controlled, evidence-based promotion list
  signal_only_mode?: boolean;  // true = signal alerts only, bot does NOT place orders
  display_timezone?: string;   // e.g. "America/New_York" | "America/Chicago" | "America/Los_Angeles"
  // Trade parameters — user-tunable without touching code
  orb_stage1_gain_pct?: number;  // Stage-1 profit target as % of entry (default 50)
  orb_stop_loss_pct?: number;    // Option premium stop-loss as % of entry (default 20)
  spread_gate_pct?: number;      // Max bid-ask spread as % of mid (default 8)
  vol_roc_threshold?: number;    // Volume ROC veto threshold (default 0.50)
  simplified_exit_mode?: boolean; // 3-rule exit (hard stop / 3.0x chandelier / time cap) vs full engine (default true)
  mtf_confirmation_enabled?: boolean; // 2026-07-23: live 1Hour bias gate, OFF by default —
                                       // can't be backtested (live "as-of-now" fetch), watch in signal-only first
  strategy_orb_pullback_v2_enabled?: boolean; // reviewed opening-range pullback strategy
  strategy_spy_trend_cont_v2_enabled?: boolean; // reviewed SPY paid-quote Trend Continuation strategy
  strategy_spy_afternoon_fvg_v2_enabled?: boolean; // reviewed SPY paid-quote afternoon FVG strategy
  strategy_spy_failed_range_recovery_v2_enabled?: boolean; // reviewed SPY failed-range recovery
  strategy_tsla_two_leg_trend_pullback_v2_enabled?: boolean; // reviewed TSLA VWAP/EMA two-leg strategy
  observe_ctx_orb_nr7_inside_enabled?: boolean;
  observe_ctx_orb_atr10_enabled?: boolean;
  observe_ctx_vwap_ker_enabled?: boolean;
  observe_ctx_vwap_displacement_enabled?: boolean;
  observe_ctx_squeeze_macd_enabled?: boolean;
  research_strategy_ids?: string[];
  opportunity_tier_enabled?: boolean; // observation-only lower-confidence research cohort; does not change account mode
  daily_loss_hard_cap_pct?: number; // 2026-07-24: 24h kill-lock threshold, was hardcoded 10% (default 10)
  min_grade_filter_enabled?: boolean; // 2026-07-24: blocks entries below min_entry_grade (default off)
  min_entry_grade?: string;           // "A+" | "A" | "B" | "C" | "Watch" (default "C")
  max_position_dollars_pct?: number;  // 2026-07-24: real per-contract affordability cap
                                       // (balance × this%), was hardcoded 15% with no UI.
}

export interface BrokerReadiness {
  provider: string;
  selected_provider?: string;
  paper: boolean;
  ready: boolean;
  checks: Record<string, { passed: boolean; detail: string }>;
}

export interface TestedStrategyInventory {
  strategies: {strategy_id: string; display_name: string; tickers: string[]; reports: string[]; report_count: number; research_supported?: boolean; research_enabled?: boolean}[];
  runtime_research?: {strategy_id: string; display_name: string; version: string; exit_minutes: number; timeframe_minutes: number; enabled: boolean; research_scope: "all_collected_tickers"}[];
  reports_scanned: number;
  other_studies: string[];
  report_details: Record<string, {title: string; purpose: string; decision: string; status: string}>;
  generated_at: string;
  unavailable?: boolean;
}

export interface ReviewedStrategyCatalogEntry {
  strategy_id: string;
  display_name: string;
  version: string;
  tickers: string[];
  setting_key: keyof AppSettings;
  signal_source: "bar_close" | "live_retouch" | "one_minute_state";
  implementation: string;
  exit_minutes: number | null;
  research_exit_minutes: number;
  paper_only: boolean;
  status: "paper_candidate" | "retired";
  evidence_grade: "passed_declared_holdout" | "promising_underpowered" | "promising_inconsistent" | "failed_profit_factor";
  evidence_artifact: string;
  evidence: string;
  backtest: {
    profit_factor?: number | string;
    trades?: number;
    scope?: string;
    comparison?: string;
    target_profit_factor?: number;
    meets_target?: boolean;
    note?: string;
    historical_test_through?: string;
    forward_evidence_start?: string;
  };
  research_scope: "all_collected_tickers";
  control_kind: "execution" | "observation";
  observation_only: boolean;
  enabled: boolean;
  account_mode: "paper" | "live";
  live_eligible: boolean;
  validation_state: "shadow_observation" | "qualified_for_live";
  observation_requires_paper_mode: boolean;
  live_promotion: {
    ready: boolean;
    stage: "shadow_observation" | "review_ready" | "live_eligible" | string;
    passed: string[];
    blockers: string[];
  };
  eligible_in_current_mode: boolean;
  execution_enabled: boolean;
  observation_enabled: boolean;
  integrity_errors: string[];
}

export interface StrategySettingChange {
  changed_at: string;
  actor_user_id: string;
  strategy_id: string;
  setting_key: string;
  previous_enabled: boolean;
  new_enabled: boolean;
}

export interface StrategyTickerRecommendation {
  strategy_id: string;
  ticker: string;
  strategy_version: string;
  display_name: string;
  evidence_summary: string;
  evidence_artifact: string;
  qualification_verified: boolean;
  metrics: Record<string, number | string | boolean | null>;
  published_at: string;
  decision: "paper_enabled" | "live_enabled" | "observing" | "pending";
  paper_enabled: boolean;
  live_enabled: boolean;
  live_eligible: boolean;
  validation_state: "shadow_observation" | "qualified_for_live";
  rollout_stage: "observing" | "approval_needed" | "paper_enabled" | "live_enabled";
  observation_requires_paper_mode: boolean;
  account_mode: "paper" | "live";
}

// ── Chart annotations (bot-drawn overlays) ────────────────────────────────────
// Emitted by strategy_router.py when a signal or veto fires.
// Frontend polls GET /api/bot/annotations/{ticker} every 5 s.
export interface NewsArticle {
  id?: number;
  headline: string;
  summary?: string;
  source?: string;
  url?: string;
  created_at?: string;
  symbols: string[];
}

export interface ChartAnnotation {
  id: string;
  type: "hline" | "zone" | "marker";
  strategy: string;         // reviewed V2 strategy ID or generic system event
  label: string;
  ts: string;               // ISO datetime
  color: string;            // hex
  direction?: string;       // "bullish" | "bearish"
  price?: number;           // hline + marker
  price_low?: number;       // zone bottom
  price_high?: number;      // zone top
}

export interface PerformanceStats {
  total_pnl: number;
  total_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  best_day: number;
  worst_day: number;
  current_streak: number;
  daily_summaries: { date: string; pnl: number; trades: number; win_rate: number }[];
  account_scoped: boolean;
  data_scope_note: string;
}

export interface BacktestResult {
  total_return_pct: number;
  win_rate_pct: number;
  total_trades: number;
  avg_win: number;
  avg_loss: number;
  sharpe: number;
  max_drawdown_pct: number;
  final_balance: number;
  stage1_rate_pct: number;
  daily_pnl: Record<string, number>;
  exit_reasons: Record<string, unknown>;
  trades: Record<string, unknown>[];
  call_trades?: number;
  put_trades?: number;
  call_win_rate?: number;
  put_win_rate?: number;
  call_pnl?: number;
  put_pnl?: number;
  strategy_breakdown?: Record<string, { trades: number; wins: number; win_rate: number; pnl: number }>;
  model_fidelity?: {
    exit_mode?: string;
    option_pricing?: string;
    limitations?: string[];
  };
  error?: string;
  holdout?: { start_date: string; end_date: string; result: BacktestResult };
}

export interface BacktestJobStatus {
  job_id: string;
  status: "queued" | "running" | "complete" | "failed";
  result?: BacktestResult;
  error?: string;
  started_at?: string;
  completed_days: number;
  total_days: number;
  estimated_remaining_seconds?: number;
}

export interface BrokerOrderEvent {
  id: number;
  event_time: string;
  event_type: string;
  status?: string | null;
  order_id?: string | null;
  filled_qty?: number | null;
  fill_price?: number | null;
  message?: string | null;
  is_issue: number | boolean;
}

export interface BrokerOrderAttempt {
  attempt_id: string;
  started_at: string;
  updated_at: string;
  order_id?: string | null;
  contract_symbol?: string | null;
  ticker?: string | null;
  strategy_id?: string | null;
  side?: string | null;
  position_intent?: string | null;
  requested_qty?: number | null;
  filled_qty?: number | null;
  fill_price?: number | null;
  final_event: string;
  final_status?: string | null;
  linked_trade_id?: number | null;
  had_issue: boolean;
  active_issue: boolean;
  issue_message?: string | null;
  events: BrokerOrderEvent[];
}

export interface BrokerOrderFlowResponse {
  date: string;
  mode: string;
  account_scoped: boolean;
  scope_note?: string;
  summary: {
    attempts: number;
    acknowledged: number;
    filled: number;
    rejected_or_failed: number;
    active_issues: number;
    unlinked_fills: number;
  };
  attempts: BrokerOrderAttempt[];
}

export interface AdminSystemHealth {
  disk: {
    status: "good" | "watch" | "critical";
    used_percent: number;
    free_bytes: number;
    total_bytes: number;
  };
}

// ── Bot ────────────────────────────────────────────────────────────────────

export const api = {
  admin: {
    systemHealth: () => request<AdminSystemHealth>("/api/admin/system-health"),
  },
  bot: {
    status:    () => request<BotStatus>("/api/bot/status"),
    start:     () => request<{ok:boolean;message:string}>("/api/bot/start", { method: "POST" }),
    stop:      () => request<{ok:boolean;message:string}>("/api/bot/stop",  { method: "POST" }),
    panic:     () => request<{ok:boolean;message:string}>("/api/bot/panic", { method: "POST" }),
    reset:     () => request<{ok:boolean;message:string}>("/api/bot/reset", { method: "POST" }),
    closeTrade:  (id: number) => request<{ok:boolean;message:string}>(`/api/bot/close/${id}`, { method: "POST" }),
    tradeEvents:   (id: number)     => request<{ts:string;level:string;component:string;message:string}[]>(`/api/bot/trade-events/${id}`),
    annotations:   (ticker: string) => request<ChartAnnotation[]>(`/api/bot/annotations/${ticker}`),
  },
  trades: {
    optionChart: (id: number, mode: "paper" | "live") =>
      request<OptionChartData>(`/api/trades/${id}/option-chart?mode=${mode}`),
    list:          (mode="paper", status="all", date?: string) => request<TradeListResponse>(
      `/api/trades?mode=${mode}&status=${status}${date ? `&date=${encodeURIComponent(date)}` : ""}`
    ),
    open:          () => request<Trade[]>("/api/trades/open"),
    performance:   (mode="paper") => request<PerformanceStats>(`/api/trades/performance?mode=${mode}`),
    analytics:     (mode="paper") => request<TradeAnalytics>(`/api/trades/analytics?mode=${mode}`),
    reconcile:     (date?: string) => request<ReconcileResponse>(`/api/trades/reconcile${date ? `?date=${date}` : ""}`),
    orderFlow:     (mode="paper", date?: string) => request<BrokerOrderFlowResponse>(
      `/api/trades/order-flow?mode=${mode}${date ? `&date=${date}` : ""}`
    ),
    /** Actual daily P&L from Alpaca portfolio history — truth, not bot estimates */
    alpacaDailyPnl: () => request<{date:string; pnl:number}[]>("/api/trades/alpaca-daily-pnl"),
  },
  market: {
    bars:    (ticker: string, tf="5Min", limit=400) => request<Bar[]>(`/api/market/bars/${ticker}?timeframe=${tf}&limit=${limit}`),
    quotes:  (tickers: string) => request<Quote[]>(`/api/market/quotes?tickers=${tickers}`),
    scanner:   () => request<ScannerResult[]>("/api/market/scanner"),
    premarket: (tickers?: string) => request<PremarketTicker[]>(
      `/api/market/premarket${tickers ? `?tickers=${encodeURIComponent(tickers)}` : ""}`
    ),
    or:      (ticker: string) => request<OpeningRange>(`/api/market/opening-range/${ticker}`),
    chain:   (ticker: string) => request<OptionsChainRow[]>(`/api/market/chain/${ticker}`),
    news:    (symbols: string, limit = 10) => request<NewsArticle[]>(`/api/market/news?symbols=${symbols}&limit=${limit}`),
  },
  learning: {
    catalog: () => request<LearningCatalogResponse>("/api/learning/catalog"),
    examples: (strategyId: string, category?: LearningExampleCategory, limit = 20) =>
      request<LearningExamplesResponse>(
        `/api/learning/examples?strategy_id=${encodeURIComponent(strategyId)}`
        + `${category ? `&category=${encodeURIComponent(category)}` : ""}`
        + `&limit=${limit}`,
      ),
    startPractice: (strategyId: string) => request<LearningPracticeStart>("/api/learning/practice/start", { method: "POST", body: JSON.stringify({ strategy_id: strategyId }) }),
    answerPractice: (sessionId: string, answer: "call" | "put" | "wait" | "reject") => request<LearningPracticeResult>(`/api/learning/practice/${encodeURIComponent(sessionId)}/answer`, { method: "POST", body: JSON.stringify({ answer }) }),
    askCoach: (exampleId: string, sessionId: string, question: string) => request<LearningCoachAnswer>("/api/learning/coach/ask", { method: "POST", body: JSON.stringify({ example_id: exampleId, session_id: sessionId, question }) }),
    rankerStatus: () => request<LearningRankerStatus>("/api/learning/ranker/status"),
  },
  settings: {
    get:  () => request<AppSettings>("/api/settings"),
    save: (s: AppSettings) => request<AppSettings>("/api/settings", { method: "POST", body: JSON.stringify(s) }),
    brokerReadiness: (paper = true) => request<BrokerReadiness>(`/api/settings/broker-readiness?paper=${paper}`),
    connectionHealth: () => request<BrokerConnectionHealth>("/api/settings/connection-health"),
    strategies: () => request<{strategies: ReviewedStrategyCatalogEntry[]}>("/api/settings/strategies"),
    testedStrategies: () => request<TestedStrategyInventory>("/api/settings/strategies/tested"),
    strategyHistory: (limit = 20) => request<{changes: StrategySettingChange[]}>(`/api/settings/strategies/history?limit=${limit}`),
    recommendations: () => request<{recommendations: StrategyTickerRecommendation[]}>("/api/settings/strategies/recommendations"),
    setRecommendation: (strategyId: string, ticker: string, decision: "paper_enabled" | "live_enabled" | "observing") =>
      request<{ok: boolean; recommendations: StrategyTickerRecommendation[]}>(
        `/api/settings/strategies/recommendations/${encodeURIComponent(strategyId)}/${encodeURIComponent(ticker)}`,
        { method: "POST", body: JSON.stringify({ decision }) },
      ),
  },
  backtest: {
    start: (
      ticker: string,
      months: number,
      capital: number,
      direction: string,
      startDate?: string,
      endDate?: string,
      riskPct?: number,       // flat override e.g. 0.05; undefined = live tier ladder
      holdoutPct?: number,
    ) =>
      request<BacktestJobStatus>("/api/backtest", {
        method: "POST",
        body: JSON.stringify({
          ticker,
          months,
          starting_capital: capital,
          direction,
          ...(startDate !== undefined ? { start_date: startDate } : {}),
          ...(endDate   !== undefined ? { end_date:   endDate   } : {}),
          ...(riskPct   !== undefined ? { risk_pct:   riskPct   } : {}),
          ...(holdoutPct !== undefined ? { holdout_pct: holdoutPct } : {}),
        }),
      }),
    status: (jobId: string) => request<BacktestJobStatus>(`/api/backtest/${jobId}`),
  },
  strategyHealth: {
    latest:  () => request<StrategyHealthAudit>("/api/strategy-health/latest"),
    history: (limit = 30) => request<{audits: StrategyHealthHistoryRow[]}>(`/api/strategy-health/history?limit=${limit}`),
    run:     () => request<StrategyHealthAudit & {ok: boolean}>("/api/strategy-health/run", { method: "POST" }),
    weeklyLatest:  () => request<WeeklyReview>("/api/strategy-health/weekly/latest"),
    weeklyHistory: (limit = 12) => request<{audits: StrategyHealthHistoryRow[]}>(`/api/strategy-health/weekly/history?limit=${limit}`),
    weeklyRun:     () => request<WeeklyReview & {ok: boolean}>("/api/strategy-health/weekly/run", { method: "POST" }),
    scorecard: (days = 30) => request<StrategyScorecard>(`/api/strategy-health/scorecard?days=${days}`),
    dailyScorecard: (mode="paper", date?: string) => request<DailyEvidenceScorecard>(
      `/api/strategy-health/daily-scorecard?mode=${mode}${date ? `&date=${date}` : ""}`
    ),
    candidateScorecard: (days = 30) => request<CandidateScorecard>(`/api/strategy-health/candidate-scorecard?days=${days}`),
    researchMatrix: (days = 90) => request<StrategyResearchMatrix>(`/api/strategy-health/research-matrix?days=${days}`),
    qqqOpeningResearch: () => request<PaperResearchScorecard>("/api/strategy-health/paper-research/qqq-opening"),
    paidTslaV2Orb: () => request<PaidResearchEvidence>("/api/strategy-health/research/paid-tsla-v2-orb"),
    paidTslaTrendProgress: () => request<PaidTrendResearchProgress>("/api/strategy-health/research/paid-tsla-trend-progress"),
    v2OrbPaperScorecard: () => request<V2OrbPaperScorecard>("/api/strategy-health/paper/v2-orb"),
  },
  aiReasoning: {
    log: (opts?: { limit?: number; eventType?: string; ticker?: string; onlyErrors?: boolean }) => {
      const params = new URLSearchParams();
      if (opts?.limit)      params.set("limit", String(opts.limit));
      if (opts?.eventType)  params.set("event_type", opts.eventType);
      if (opts?.ticker)     params.set("ticker", opts.ticker);
      if (opts?.onlyErrors) params.set("only_errors", "true");
      const qs = params.toString();
      return request<{ entries: AiReasoningEntry[]; count: number }>(
        `/api/ai-reasoning/log${qs ? `?${qs}` : ""}`
      );
    },
    entry: (id: number) => request<AiReasoningEntry>(`/api/ai-reasoning/log/${id}`),
  },
  signals: {
    journal: (opts?: { ticker?: string; strategy?: string; reason?: string; limit?: number }) => {
      const params = new URLSearchParams();
      if (opts?.ticker)   params.set("ticker", opts.ticker);
      if (opts?.strategy) params.set("strategy", opts.strategy);
      if (opts?.reason)   params.set("reason", opts.reason);
      if (opts?.limit)    params.set("limit", String(opts.limit));
      const qs = params.toString();
      return request<{ entries: SignalJournalEntry[]; count: number }>(
        `/api/signals/journal${qs ? `?${qs}` : ""}`
      );
    },
    summary: () => request<SignalJournalSummary>("/api/signals/journal/summary"),
    trend:   (reason: string, days = 7) =>
      request<{ reason: string; days: number; points: SignalJournalTrendPoint[] }>(
        `/api/signals/journal/trend?reason=${encodeURIComponent(reason)}&days=${days}`
      ),
    reasons: () => request<{ reasons: Record<string, string> }>("/api/signals/journal/reasons"),
    opportunities: (opts?: { date?: string; ticker?: string; strategy?: string; outcome?: string; feed?: "operational" | "research"; limit?: number }) => {
      const params = new URLSearchParams();
      if (opts?.date)     params.set("date", opts.date);
      if (opts?.ticker)   params.set("ticker", opts.ticker);
      if (opts?.strategy) params.set("strategy", opts.strategy);
      if (opts?.outcome)  params.set("outcome", opts.outcome);
      if (opts?.feed)     params.set("feed", opts.feed);
      if (opts?.limit)    params.set("limit", String(opts.limit));
      const qs = params.toString();
      return request<ScannerOpportunitiesResponse>(`/api/signals/opportunities${qs ? `?${qs}` : ""}`);
    },
    gateScorecard: (days = 30) => request<GateCalibrationScorecard>(`/api/signals/gate-scorecard?days=${days}`),
    watching: () => request<{ watching: WatchingSignal[] }>("/api/signals/watching"),
  },
  tickers: {
    board: () => request<{ tickers: TickerBoardRow[] }>("/api/tickers/board"),
  },
};
