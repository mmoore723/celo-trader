/**
 * lib/api.ts — Typed API client for all FastAPI endpoints.
 */

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
  account_balance: number;
  day_start_balance: number;   // Alpaca equity captured at bot startup — never derived
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
  blocked: number; pending: number; measured: number; correct: number;
  directional_win_rate: number | null; avg_directional_move_pct: number | null;
  block_reasons: Record<string, number>;
}
export interface CandidateScorecard {
  days: number; account_scoped: boolean; note: string;
  strategies: CandidateScorecardRow[];
}
export interface PaperResearchScorecard {
  study_id: string; observations: number; closed: number; unavailable: number;
  quote_measured: number; option_win_rate_pct: number | null;
  avg_underlying_move_pct: number | null; avg_executable_return_pct: number | null;
  note: string;
}
export interface PaidResearchEvidence {
  study_id: string; label: string; status: "paper_validation_next";
  ticker: string; strategy_id: string; data_scope: string; execution_model: string;
  baseline: { label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number };
  unseen_holdout: { label: string; measured_signals: number; win_rate_pct: number; average_return_pct: number };
  walkforward: {
    label: string;
    baseline: { measured_signals: number; average_return_pct: number };
    best_past_variant: { measured_signals: number; average_return_pct: number };
  };
  uncertainty: { label: string; low_pct: number; high_pct: number; interpretation: string };
  what_changed: string; next_step: string; caveat: string;
}

export interface Trade {
  id: number;
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

export interface WatchingContract {
  symbol: string | null;
  strike: number | null;
  expiry: string | null;
  bid: number | null;
  ask: number | null;
}

export interface WatchingSignal {
  ticker: string;
  strategy: string;              // "INST_ORB" — only strategy with a waiting state today
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
  entry_note: string;
  stop_note: string;
  target_note: string;
  key_levels: { label: string; price: number; type: string }[];
  setup_notes: string;
  is_pinned: boolean;
  rank: number;
}

export interface AppSettings {
  paper_trading?: boolean;   // true = paper (default), false = live; only toggled via Settings
  risk_pct: number;
  risk_auto?: boolean;       // true = use the balance-based tier, not a manual override
  growth_mode: boolean;
  flip_trading_enabled: boolean;
  max_concurrent_positions: number;
  rr_ratio_mode: string;
  watchlist: string[];
  validated_strategy_ids?: string[]; // server-controlled, evidence-based promotion list
  orb_enabled: boolean;
  vwap_pullback_enabled: boolean;
  fvg_enabled: boolean;
  ifvg_enabled: boolean;          // Inverted Fair Value Gap
  bos_mss_enabled: boolean;
  chan_break_enabled: boolean;
  mid_brk_enabled: boolean;
  trend_cont_enabled: boolean;
  aft_rev_enabled: boolean;    // Afternoon Reversal — added to Settings 2026-07-20
  gap_go_enabled?: boolean;    // Gap and Go — added 2026-07-23, OFF by default (untested live)
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
  inst_orb_immediate_entry_enabled?: boolean; // 2026-07-31: enter on the breakout bar instead of
                                       // waiting for the OR-level retest, ON by default — not backtested
  liquidity_sweep_enabled?: boolean;  // 2026-07-31: fades a swept swing high/low, ON by
                                       // default — new strategy, no backtest track record
  strategy_orb_pullback_v2_enabled?: boolean; // research-validated opening-range pullback pilot
  opportunity_tier_enabled?: boolean; // paper-only lower-confidence research cohort
  daily_loss_hard_cap_pct?: number; // 2026-07-24: 24h kill-lock threshold, was hardcoded 10% (default 10)
  min_grade_filter_enabled?: boolean; // 2026-07-24: blocks entries below min_entry_grade (default off)
  min_entry_grade?: string;           // "A+" | "A" | "B" | "C" | "Watch" (default "C")
  max_position_dollars_pct?: number;  // 2026-07-24: real per-contract affordability cap
                                       // (balance × this%), was hardcoded 15% with no UI.
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
  strategy: string;         // "FVG" | "BOS_MSS" | "veto" | …
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

// ── Bot ────────────────────────────────────────────────────────────────────

export const api = {
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
    list:          (mode="paper", status="all") => request<TradeListResponse>(`/api/trades?mode=${mode}&status=${status}`),
    open:          () => request<Trade[]>("/api/trades/open"),
    performance:   (mode="paper") => request<PerformanceStats>(`/api/trades/performance?mode=${mode}`),
    analytics:     (mode="paper") => request<TradeAnalytics>(`/api/trades/analytics?mode=${mode}`),
    reconcile:     (date?: string) => request<ReconcileResponse>(`/api/trades/reconcile${date ? `?date=${date}` : ""}`),
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
    or:      (ticker: string) => request<Record<string,number>>(`/api/market/opening-range/${ticker}`),
    chain:   (ticker: string) => request<OptionsChainRow[]>(`/api/market/chain/${ticker}`),
    news:    (symbols: string, limit = 10) => request<NewsArticle[]>(`/api/market/news?symbols=${symbols}&limit=${limit}`),
  },
  settings: {
    get:  () => request<AppSettings>("/api/settings"),
    save: (s: AppSettings) => request<AppSettings>("/api/settings", { method: "POST", body: JSON.stringify(s) }),
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
    candidateScorecard: (days = 30) => request<CandidateScorecard>(`/api/strategy-health/candidate-scorecard?days=${days}`),
    qqqOpeningResearch: () => request<PaperResearchScorecard>("/api/strategy-health/paper-research/qqq-opening"),
    paidTslaV2Orb: () => request<PaidResearchEvidence>("/api/strategy-health/research/paid-tsla-v2-orb"),
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
    watching: () => request<{ watching: WatchingSignal[] }>("/api/signals/watching"),
  },
  tickers: {
    board: () => request<{ tickers: TickerBoardRow[] }>("/api/tickers/board"),
  },
};
