/**
 * TradeChartModal.tsx — full-screen chart modal for simulation and replay.
 * Replaces ChartModal.tsx (which rendered the old, frozen TradingChart).
 * Journal's "View on Chart" now gets the same boomerang replay + narration
 * as Live Trading, not a separate static view.
 */
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Trade } from "../../lib/api";
import { TradeChart } from "./TradeChart";
import { BoomerangReplay, type BoomerangReplayHandle } from "./BoomerangReplay";
import type { SimulationOverlay, ReplayTrade } from "../../lib/chart_types";

interface BaseProps { open: boolean; onClose: () => void; ticker: string }
interface SimulationProps extends BaseProps { mode: "simulation"; simulationOverlay: SimulationOverlay; date?: string }
interface ReplayProps extends BaseProps { mode: "replay"; trade: Trade }
type Props = SimulationProps | ReplayProps;

function toReplayTrade(t: Trade): ReplayTrade {
  return {
    entry_time: t.entry_time ?? "", exit_time: t.exit_time,
    entry_option_px: t.entry_price, exit_option_px: t.exit_price,
    peak_option_px: t.peak_price, mae_option_px: t.mae_price,
    direction: t.direction === "short" ? "short" : "long",
    exit_reason: t.exit_reason, pnl: t.pnl, contracts: t.contracts,
  };
}
function tradeDateStr(t: Trade): string {
  return t.entry_time ? t.entry_time.slice(0, 10) : new Date().toISOString().slice(0, 10);
}

export function TradeChartModal(props: Props) {
  const { open, onClose, ticker } = props;
  const [tf, setTf] = useState("5Min");
  const replayRef = useRef<BoomerangReplayHandle>(null);
  const date = props.mode === "simulation" ? (props.date ?? new Date().toISOString().slice(0, 10)) : tradeDateStr(props.trade);

  const { data: bars = [], isLoading } = useQuery({
    queryKey: ["chart-modal-bars", ticker, tf],
    queryFn: () => api.market.bars(ticker, tf, 400),
    enabled: open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);

  // Kick off the boomerang the moment bars are ready for a replay.
  useEffect(() => {
    if (open && props.mode === "replay" && bars.length > 0 && props.trade.entry_time) {
      replayRef.current?.jumpToTime(props.trade.entry_time, props.trade.exit_time);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, props.mode, bars.length]);

  if (!open) return null;
  const replayTrade = props.mode === "replay" ? toReplayTrade(props.trade) : undefined;
  const simOverlay = props.mode === "simulation" ? props.simulationOverlay : undefined;
  const tradesForChart = props.mode === "replay" ? [props.trade] : [];
  const chartHeight = Math.min(window.innerHeight * 0.92, 820) - 52 - 100;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 9000, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center" }}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ width: "min(98vw, 1280px)", height: "min(92vh, 820px)", background: "var(--panel)", borderRadius: 12, border: "1px solid var(--border)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)" }}>{ticker}</span>
            <span style={{ fontSize: 11, color: "var(--ink-muted)" }}>
              {props.mode === "simulation" ? "Pre-Trade Simulation" : `Trade Replay · ${date}`}
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              {(["1Min", "5Min", "15Min", "1Hour"] as const).map((t) => (
                <button key={t} onClick={() => setTf(t)} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 4, cursor: "pointer", background: tf === t ? "var(--accent)" : "transparent", color: tf === t ? "#fff" : "var(--ink-muted)", border: `1px solid ${tf === t ? "var(--accent)" : "var(--border)"}` }}>
                  {t.replace("Min", "m").replace("Hour", "H")}
                </button>
              ))}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-muted)" }}><X size={18} /></button>
        </div>

        <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
          {isLoading ? (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--ink-muted)", fontSize: 13 }}>Loading bars…</div>
          ) : props.mode === "replay" ? (
            <BoomerangReplay
              ref={replayRef}
              mode="historical"
              bars={bars} trades={tradesForChart} ticker={ticker}
              height={chartHeight} showOR={false} showSwings showStructure
              replayTrade={replayTrade}
              staticNarration={props.trade.recap}
            />
          ) : (
            <TradeChart bars={bars} trades={tradesForChart} ticker={ticker} height={chartHeight} showOR={false} simulationOverlay={simOverlay} />
          )}
        </div>

        {props.mode === "replay" && (
          <div style={{ padding: "8px 16px", borderTop: "1px solid var(--border)", display: "flex", gap: 24, fontSize: 11, color: "var(--ink-muted)" }}>
            <span>Entry <b style={{ color: "var(--ink)" }}>${props.trade.entry_price?.toFixed(2)}</b></span>
            {props.trade.exit_price && <span>Exit <b style={{ color: "var(--ink)" }}>${props.trade.exit_price.toFixed(2)}</b></span>}
            {props.trade.pnl != null && <span>P&L <b style={{ color: props.trade.pnl >= 0 ? "#26a69a" : "#ef5350" }}>{props.trade.pnl >= 0 ? "+" : ""}${props.trade.pnl.toFixed(2)}</b></span>}
          </div>
        )}
        {props.mode === "simulation" && (
          <div style={{ padding: "8px 16px", borderTop: "1px solid var(--border)", display: "flex", gap: 24, fontSize: 11, color: "var(--ink-muted)" }}>
            <span>Direction <b style={{ color: props.simulationOverlay.direction === "calls" ? "#26a69a" : "#ef5350" }}>{props.simulationOverlay.direction.toUpperCase()}</b></span>
            <span>Grade <b style={{ color: "var(--ink)" }}>{props.simulationOverlay.grade}</b></span>
            <span>Entry Trigger <b style={{ color: "var(--ink)" }}>${props.simulationOverlay.entryTrigger.toFixed(2)}</b></span>
          </div>
        )}
      </div>
    </div>
  );
}
