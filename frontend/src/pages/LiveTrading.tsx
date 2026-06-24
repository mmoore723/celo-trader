/**
 * LiveTrading.tsx — Main trading cockpit.
 * Real-time chart, open positions, bot eval log, scanner.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { TradingChart } from "../components/charts/TradingChart";
import { useBotStore } from "../store/bot";
import { api, type Trade } from "../lib/api";

const TICKERS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "MSFT"];

function PnlBadge({ value }: { value?: number }) {
  if (value == null) return <span className="text-ink-muted">—</span>;
  return (
    <span style={{ color: value >= 0 ? "var(--positive)" : "var(--negative)" }}>
      {value >= 0 ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

export function LiveTrading() {
  const [ticker, setTicker] = useState("SPY");
  const [tf, setTf] = useState("5Min");
  const [showVwap, setShowVwap] = useState(true);
  const [showVwapBands, setShowVwapBands] = useState(true);
  const [showOR, setShowOR] = useState(true);
  const [showSwings, setShowSwings] = useState(true);
  const { status, logs } = useBotStore();

  const { data: bars = [], isLoading: barsLoading } = useQuery({
    queryKey: ["bars", ticker, tf],
    queryFn: () => api.market.bars(ticker, tf, 200),
    refetchInterval: 60_000,
  });

  const { data: openTrades = [] } = useQuery({
    queryKey: ["open-trades"],
    queryFn: api.trades.open,
    refetchInterval: 5_000,
  });

  const { data: scanner = [] } = useQuery({
    queryKey: ["scanner"],
    queryFn: api.market.scanner,
    refetchInterval: 60_000,
  });

  const { data: or } = useQuery({
    queryKey: ["or", ticker],
    queryFn: () => api.market.or(ticker),
    enabled: showOR,
    refetchInterval: 300_000,
  });

  // Trades for the current ticker
  const tickerTrades = openTrades.filter((t: Trade) => t.ticker === ticker);

  // Build position levels from first open trade on this ticker (if any)
  const openTickerTrade = tickerTrades.find((t: Trade) => !t.exit_time);
  const positionLevels = openTickerTrade ? {
    entry:     openTickerTrade.entry_price  ?? undefined,
    stop:      openTickerTrade.stop_price   ?? undefined,
    target:    openTickerTrade.target_price ?? undefined,
    trail:     (openTickerTrade as any).trail_price ?? undefined,
    direction: (openTickerTrade.direction === "short" ? "short" : "long") as "long" | "short",
    contracts: openTickerTrade.contracts    ?? undefined,
  } : undefined;

  return (
    <div className="p-4 flex flex-col gap-4">
      {/* Stat bar */}
      <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap sm:gap-3">
        {[
          { label: "Balance",    value: `$${(status?.account_balance ?? 0).toFixed(2)}` },
          { label: "Session P&L",value: <PnlBadge value={status?.session_pnl} /> },
          { label: "Opt BP",     value: `$${(status?.options_buying_power ?? 0).toFixed(2)}` },
          { label: "Open",       value: openTrades.length },
          { label: "Signal",     value: status?.last_strategy_id ?? "—" },
          { label: "Mode",       value: (status?.mode ?? "—").toUpperCase() },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-2.5 flex flex-col gap-0.5 min-w-[110px]">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num font-semibold text-sm" style={{ color: "var(--ink)" }}>
              {s.value}
            </span>
          </div>
        ))}
      </div>

      {/* Main grid: chart + scanner */}
      <div className="grid gap-4 chart-scanner-grid">
        {/* Chart panel */}
        <div className="card overflow-hidden">
          {/* Chart toolbar */}
          <div
            className="flex items-center gap-3 px-3 py-2 border-b text-sm"
            style={{ borderColor: "var(--border)" }}
          >
            {/* Ticker selector */}
            <select
              className="select"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
            >
              {TICKERS.map((t) => <option key={t}>{t}</option>)}
            </select>

            {/* Timeframe */}
            <div className="flex gap-1">
              {(["1Min","5Min","15Min","1Hour"] as const).map((t) => (
                <button
                  key={t}
                  className={`btn btn-sm ${tf === t ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setTf(t)}
                >
                  {t.replace("Min","m").replace("Hour","h")}
                </button>
              ))}
            </div>

            {/* Overlay toggles */}
            {([
              ["VWAP",    showVwap,      setShowVwap],
              ["Bands",   showVwapBands, setShowVwapBands],
              ["OR",      showOR,        setShowOR],
              ["Swings",  showSwings,    setShowSwings],
            ] as [string, boolean, (v: boolean) => void][]).map(([label, val, setter]) => (
              <label key={label} className="flex items-center gap-1 cursor-pointer text-xs"
                     style={{ color: "var(--ink-muted)" }}>
                <input type="checkbox" checked={val}
                       onChange={(e) => setter(e.target.checked)} />
                {label}
              </label>
            ))}

            <div className="flex-1" />
            {barsLoading && <RefreshCw size={13} className="animate-spin text-ink-muted" />}
          </div>

          <TradingChart
            bars={bars}
            trades={tickerTrades}
            showVwap={showVwap}
            showVwapBands={showVwapBands}
            showOR={showOR}
            showSwings={showSwings}
            orHigh={or?.high}
            orLow={or?.low}
            positionLevels={positionLevels}
            ticker={ticker}
            height={420}
          />
        </div>

        {/* Scanner panel */}
        <div className="card flex flex-col">
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Premarket Scanner
          </div>
          <div className="overflow-y-auto">
            {scanner.length === 0 ? (
              <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                No scan results yet — bot scans 9:00–9:25 ET
              </p>
            ) : (
              scanner.map((s) => (
                <button
                  key={s.ticker}
                  className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-muted transition-colors text-left"
                  onClick={() => setTicker(s.ticker)}
                >
                  <div>
                    <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                      {s.ticker}
                    </div>
                    <div className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                      ${s.price.toFixed(2)} · {s.rvol.toFixed(1)}x RVOL
                    </div>
                  </div>
                  <span
                    className="text-xs num font-medium"
                    style={{ color: s.change_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
                  >
                    {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                  </span>
                </button>
              ))
            )}
          </div>

          {/* Pending signal — what the bot is looking to enter */}
          <div
            className="border-t px-3 py-2 text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Bot Focus
          </div>
          <div className="px-3 pb-3 flex flex-col gap-1.5">
            {status?.ticker ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm" style={{ color: "var(--ink)" }}>
                    {status.ticker}
                  </span>
                  {status.last_strategy_id && (
                    <span className="badge badge-blue">{status.last_strategy_id}</span>
                  )}
                </div>
                {status.last_signal && (
                  <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                    {status.last_signal}
                  </p>
                )}
                {status.current_stop_pct != null && (
                  <div className="text-xs num" style={{ color: "var(--negative)" }}>
                    Stop: {(status.current_stop_pct * 100).toFixed(1)}% from entry
                  </div>
                )}
              </>
            ) : (
              <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
                Waiting for bot to start scanning…
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Open positions + eval log */}
      <div className="grid gap-4 two-col-grid">
        {/* Open positions */}
        <div className="card">
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Open Positions ({openTrades.length})
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Dir</th><th>Entry</th>
                  <th>Strategy</th><th>P&L</th><th></th>
                </tr>
              </thead>
              <tbody>
                {openTrades.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-6" style={{ color: "var(--ink-muted)" }}>
                      No open positions
                    </td>
                  </tr>
                ) : (
                  openTrades.map((t: Trade) => (
                    <tr key={t.id}>
                      <td className="font-semibold">{t.ticker}</td>
                      <td>
                        <span className={`badge ${t.direction === "long" ? "badge-green" : "badge-red"}`}>
                          {t.direction?.toUpperCase()}
                        </span>
                      </td>
                      <td className="num">${t.entry_price.toFixed(2)}</td>
                      <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                        {t.strategy_id ?? "—"}
                      </td>
                      <td><PnlBadge value={t.pnl} /></td>
                      <td>
                        <button
                          className="btn btn-ghost btn-sm text-xs"
                          onClick={() => api.bot.closeTrade(t.id)}
                        >
                          Close
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Bot eval log */}
        <div className="card flex flex-col">
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Bot Thinking
          </div>
          <div
            className="flex-1 overflow-y-auto p-2 flex flex-col gap-1 font-mono text-xs"
            style={{ maxHeight: 280 }}
          >
            {logs.slice(0, 80).map((entry, i) => {
              const lvl = (entry.level ?? "INFO").toUpperCase();
              const color =
                lvl === "ERROR"   ? "var(--negative)" :
                lvl === "WARNING" ? "var(--warning)"  :
                entry.event?.includes("Trade_Signal") ? "var(--positive)" :
                "var(--ink-muted)";
              return (
                <div key={i} style={{ color }}>
                  <span className="opacity-60">{entry.ts ?? ""}</span>{" "}
                  {entry.event && (
                    <span className="badge badge-blue mr-1">{entry.event}</span>
                  )}
                  {String(entry.message ?? "")}
                </div>
              );
            })}
            {logs.length === 0 && (
              <p style={{ color: "var(--ink-muted)" }}>Waiting for bot…</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
