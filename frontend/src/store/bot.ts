/**
 * store/bot.ts — Zustand store for real-time bot state from WebSocket.
 */
import { create } from "zustand";

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
  is_paper: boolean;               // true = paper account, false = live account
  // Contract eval snapshot — populated after each signal evaluation
  last_eval_strike: number | null;
  last_eval_expiry: string | null;
  last_eval_contract_symbol: string | null;
  last_eval_eff_entry: number | null;
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
