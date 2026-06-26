/**
 * store/bot.ts — Zustand store for real-time bot state from WebSocket.
 */
import { create } from "zustand";

/** Live per-position data written to bot_state.json every tick. */
export interface LivePosition {
  trade_id: number;
  contract_symbol: string;
  ticker: string;
  option_type: string;       // "call" | "put"
  entry_price: number;
  contracts: number;
  current_option_price: number | null;
  current_option_price_time: string | null;
  stage1_done: boolean;
  peak_price: number | null;
  entry_time: string | null;
  atr_trail_stop: number | null;
  current_stop_pct: number | null;
  vwap_breached_bars: number;
  trend_dead: boolean;
}

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
  is_paper: boolean;
  // Live open positions — keyed by trade_id string
  open_positions: Record<string, LivePosition> | null;
  // Contract eval snapshot — populated after each signal evaluation
  last_eval_strike: number | null;
  last_eval_expiry: string | null;
  last_eval_contract_symbol: string | null;
  last_eval_eff_entry: number | null;
  // Scanner watchlist — full list of tickers the bot is cycling through
  scan_watchlist: string[] | null;
  current_scan_idx: number | null;
}

export interface LogEntry {
  ts?: string;
  message: string;
  level: string;
  event?: string;
  ticker?: string;
  [key: string]: unknown;
}

interface BotStore {
  status: BotStatus | null;
  logs: LogEntry[];
  connected: boolean;
  setStatus: (s: BotStatus) => void;
  addLog: (e: LogEntry) => void;
  clearLogs: () => void;
  setConnected: (v: boolean) => void;
}

export const useBotStore = create<BotStore>((set) => ({
  status: null,
  logs: [],
  connected: false,
  setStatus: (s) => set({ status: s }),
  addLog: (e) =>
    set((st) => ({ logs: [e, ...st.logs].slice(0, 300) })), // keep last 300
  clearLogs: () => set({ logs: [] }),
  setConnected: (v) => set({ connected: v }),
}));
