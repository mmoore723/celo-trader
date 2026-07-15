/**
 * ChartModal.tsx — Full-screen chart modal for simulation and replay.
 *
 * Modes:
 *   "simulation" — shows projected ORB zone, entry trigger, Stage 1 target, stop
 *   "replay"     — shows a past trade's entry / exit / MFE / MAE on the actual day's chart
 *
 * Used by:
 *   DailyBrief.tsx  — "Simulate" button on premarket ticker
 *   Journal.tsx     — "View on Chart" button on closed trade
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Trade } from "../../lib/api";
import { TradingChart } from "./TradingChart";
import type { SimulationOverlay, ReplayTrade } from "../../lib/chart_types";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BaseProps {
  open: boolean;
  onClose: () => void;
  ticker: string;
}

interface SimulationProps extends BaseProps {
  mode: "simulation";
  simulationOverlay: SimulationOverlay;
  date?: string;   // YYYY-MM-DD; defaults to today
}

interface ReplayProps extends BaseProps {
  mode: "replay";
  trade: Trade;
}

type Props = SimulationProps | ReplayProps;

// ── Helper: derive ReplayTrade from closed Trade record ───────────────────────

function toReplayTrade(t: Trade): ReplayTrade {
  return {
    entry_time:     t.entry_time ?? "",
    exit_time:      t.exit_time,
    entry_option_px: t.entry_price,
    exit_option_px:  t.exit_price,
    peak_option_px:  t.peak_price,
    mae_option_px:   t.mae_price,
    direction:      t.direction === "short" ? "short" : "long",
    exit_reason:    t.exit_reason,
    pnl:            t.pnl,
    contracts:      t.contracts,
  };
}

// ── Helper: derive the date string from a trade's entry_time ─────────────────

function tradeDateStr(t: Trade): string {
  if (!t.entry_time) return new Date().toISOString().slice(0, 10);
  return t.entry_time.slice(0, 10);   // "2025-07-14"
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChartModal(props: Props) {
  const { open, onClose, ticker } = props;
  const [tf, setTf] = useState("5Min");

  // Determine bar-fetch date
  const date = props.mode === "simulation"
    ? (props.date ?? new Date().toISOString().slice(0, 10))
    : tradeDateStr(props.trade);

  // Fetch OHLCV bars — 400-bar limit covers 30 days at 5Min, 7 days at 1Min.
  // The bars endpoint always returns recent history; trade markers snap to
  // the correct timestamps within that window (replay works for recent trades).
  const { data: bars = [], isLoading } = useQuery({
    queryKey: ["chart-modal-bars", ticker, tf],
    queryFn:  () => api.market.bars(ticker, tf, 400),
    enabled:  open,
    staleTime: 60_000,
  });

  // Keyboard close
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);

  if (!open) return null;

  const replayTrade = props.mode === "replay" ? toReplayTrade(props.trade) : undefined;
  const simOverlay  = props.mode === "simulation" ? props.simulationOverlay : undefined;

  // For replay: pass the trade as the trades array so entry/exit markers render
  const tradesForChart = props.mode === "replay" ? [props.trade] : [];

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9000,
        background: "rgba(0,0,0,0.75)", display: "flex",
        alignItems: "center", justifyContent: "center",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          width: "min(98vw, 1280px)", height: "min(92vh, 820px)",
          background: "var(--panel)", borderRadius: 12,
          border: "1px solid var(--border)",
          display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "10px 16px", borderBottom: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)" }}>
              {ticker}
            </span>
            <span style={{ fontSize: 11, color: "var(--ink-muted)" }}>
              {props.mode === "simulation" ? "📊 Pre-Trade Simulation" : `⏪ Trade Replay · ${date}`}
            </span>
            {/* TF selector */}
            <div style={{ display: "flex", gap: 4 }}>
              {(["1Min", "5Min", "15Min", "1Hour"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTf(t)}
                  style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 4, cursor: "pointer",
                    background: tf === t ? "var(--accent)" : "transparent",
                    color: tf === t ? "#fff" : "var(--ink-muted)",
                    border: `1px solid ${tf === t ? "var(--accent)" : "var(--border)"}`,
                  }}
                >
                  {t.replace("Min", "m").replace("Hour", "H")}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-muted)" }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Chart area */}
        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
          {isLoading ? (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              color: "var(--ink-muted)", fontSize: 13,
            }}>
              Loading bars…
            </div>
          ) : (
            <TradingChart
              bars={bars}
              trades={tradesForChart}
              ticker={ticker}
              height={Math.min(window.innerHeight * 0.92, 820) - 52 - 100}
              showVwap
              showVwapBands
              showOR={false}
              showSwings={props.mode === "replay"}
              showPositionCard={false}
              showRsi
              showMacd
              simulationOverlay={simOverlay}
              replayTrade={replayTrade}
            />
          )}
        </div>

        {/* Footer: context panel */}
        {props.mode === "replay" && (
          <div style={{
            padding: "8px 16px", borderTop: "1px solid var(--border)",
            display: "flex", gap: 24, fontSize: 11, color: "var(--ink-muted)",
          }}>
            <span>Entry <b style={{ color: "var(--ink)" }}>${props.trade.entry_price?.toFixed(2)}</b></span>
            {props.trade.exit_price && <span>Exit <b style={{ color: "var(--ink)" }}>${props.trade.exit_price.toFixed(2)}</b></span>}
            {props.trade.peak_price && <span>MFE <b style={{ color: "#a78bfa" }}>${props.trade.peak_price.toFixed(2)}</b></span>}
            {props.trade.mae_price  && <span>MAE <b style={{ color: "#f87171" }}>${props.trade.mae_price.toFixed(2)}</b></span>}
            {props.trade.pnl != null && (
              <span>P&L <b style={{ color: props.trade.pnl >= 0 ? "#26a69a" : "#ef5350" }}>
                {props.trade.pnl >= 0 ? "+" : ""}${props.trade.pnl.toFixed(2)}
              </b></span>
            )}
            {props.trade.exit_reason && <span>Exit: <b style={{ color: "var(--ink)" }}>{props.trade.exit_reason}</b></span>}
          </div>
        )}

        {props.mode === "simulation" && (
          <div style={{
            padding: "8px 16px", borderTop: "1px solid var(--border)",
            display: "flex", gap: 24, fontSize: 11, color: "var(--ink-muted)",
          }}>
            <span>Direction <b style={{ color: props.simulationOverlay.direction === "calls" ? "#26a69a" : "#ef5350" }}>
              {props.simulationOverlay.direction.toUpperCase()}
            </b></span>
            <span>Grade <b style={{ color: "var(--ink)" }}>{props.simulationOverlay.grade}</b></span>
            <span>Entry Trigger <b style={{ color: "var(--ink)" }}>${props.simulationOverlay.entryTrigger.toFixed(2)}</b></span>
            <span>Stage 1 <b style={{ color: "#26a69a" }}>${props.simulationOverlay.stage1Px.toFixed(2)}</b></span>
            <span>Stop <b style={{ color: "#ef5350" }}>${props.simulationOverlay.stopPx.toFixed(2)}</b></span>
            <span>ATR <b style={{ color: "var(--ink)" }}>${props.simulationOverlay.atr.toFixed(2)}</b></span>
          </div>
        )}
      </div>
    </div>
  );
}
