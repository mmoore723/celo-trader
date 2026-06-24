/**
 * lib/api.ts — Typed API client for all FastAPI endpoints.
 */

const BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
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
  session_pnl: number;
  options_buying_power: number;
  last_update: string | null;
  network_ok: boolean;
  last_strategy_id: string | null;
  current_stop_pct: number | null;
  last_signal: string | null;
  ghost_position_detected: boolean;
}

export interface Trade {
  id: number;
  ticker: string;
  direction: string;
  option_type?: string;
  strategy_id?: string;
  entry_price: number;
  exit_price?: number;
  contracts: number;
  pnl?: number;
  status: string;
  entry_time?: string;
  exit_time?: string;
  exit_reason?: string;
  stage1_done?: boolean;
  mode?: string;
}

export interface TradeListResponse {
  trades: Trade[];
  total: number;
  total_pnl: number;
  win_rate: number;
}

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
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

export interface AppSettings {
  risk_pct: number;
  growth_mode: boolean;
  flip_trading_enabled: boolean;
  max_concurrent_positions: number;
  rr_ratio_mode: string;
  watchlist: string[];
  orb_enabled: boolean;
  vwap_pullback_enabled: boolean;
  fvg_enabled: boolean;
  bos_mss_enabled: boolean;
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
  error?: string;
}

// ── Bot ────────────────────────────────────────────────────────────────────

export const api = {
  bot: {
    status:    () => request<BotStatus>("/api/bot/status"),
    start:     (mode = "paper") => request<{ok:boolean;message:string}>(`/api/bot/start?mode=${mode}`, { method: "POST" }),
    stop:      () => request<{ok:boolean;message:string}>("/api/bot/stop",  { method: "POST" }),
    panic:     () => request<{ok:boolean;message:string}>("/api/bot/panic", { method: "POST" }),
    reset:     () => request<{ok:boolean;message:string}>("/api/bot/reset", { method: "POST" }),
    closeTrade:(id: number) => request<{ok:boolean;message:string}>(`/api/bot/close/${id}`, { method: "POST" }),
  },
  trades: {
    list:        (mode="paper", status="all") => request<TradeListResponse>(`/api/trades?mode=${mode}&status=${status}`),
    open:        () => request<Trade[]>("/api/trades/open"),
    performance: (mode="paper") => request<PerformanceStats>(`/api/trades/performance?mode=${mode}`),
  },
  market: {
    bars:    (ticker: string, tf="5Min", limit=200) => request<Bar[]>(`/api/market/bars/${ticker}?timeframe=${tf}&limit=${limit}`),
    quotes:  (tickers: string) => request<Quote[]>(`/api/market/quotes?tickers=${tickers}`),
    scanner: () => request<ScannerResult[]>("/api/market/scanner"),
    or:      (ticker: string) => request<Record<string,number>>(`/api/market/opening-range/${ticker}`),
  },
  settings: {
    get:  () => request<AppSettings>("/api/settings"),
    save: (s: AppSettings) => request<AppSettings>("/api/settings", { method: "POST", body: JSON.stringify(s) }),
  },
  backtest: {
    run: (ticker: string, months: number, capital: number) =>
      request<BacktestResult>("/api/backtest", {
        method: "POST",
        body: JSON.stringify({ ticker, months, starting_capital: capital }),
      }),
  },
};
