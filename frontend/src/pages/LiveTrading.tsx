/**
 * LiveTrading.tsx — Main trading cockpit.
 * Real-time chart, open positions, bot eval log, scanner with mini sparklines.
 */
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import {
  AreaChart, Area, ResponsiveContainer, YAxis,
} from "recharts";
import { TradingChart } from "../components/charts/TradingChart";
import { useBotStore } from "../store/bot";
import { api, type Trade, type Bar } from "../lib/api";

const TICKERS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "MSFT"];

// ── Period helper ───────────────────────────────────────────────────────────
type Period = "1D" | "5D" | "1M" | "3M";

function filterByPeriod(bars: Bar[], period: Period): Bar[] {
  if (!bars.length) return bars;
  const now = new Date();
  const ms: Record<Period, number> = {
    "1D":  1  * 24 * 60 * 60 * 1000,
    "5D":  5  * 24 * 60 * 60 * 1000,
    "1M":  30 * 24 * 60 * 60 * 1000,
    "3M":  90 * 24 * 60 * 60 * 1000,
  };
  const cutoff = new Date(now.getTime() - ms[period]);
  return bars.filter((b) => new Date(b.time) >= cutoff);
}

// ── Mini sparkline for scanner ──────────────────────────────────────────────
function MiniSparkline({ bars, color }: { bars: Bar[]; color: string }) {
  if (!bars.length) return <div style={{ height: 40, width: "100%" }} />;
  const data = bars.slice(-30).map((b) => ({ v: b.close }));
  return (
    <ResponsiveContainer width="100%" height={40}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
        <defs>
          <linearGradient id={`sg-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.25} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis domain={["auto", "auto"]} hide />
        <Area
          type="monotone" dataKey="v"
          stroke={color} strokeWidth={1.5}
          fill={`url(#sg-${color.replace("#", "")})`}
          dot={false} isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Classify a log entry as network-related (broker/API) vs a trading decision.
// Network: module contains broker/alpaca/tradier keywords or message has API noise.
// Separator entries from the WebSocket (previous-session divider)
function isSeparator(entry: Record<string, unknown>): boolean {
  return !!entry["_separator"];
}

function isNetworkLog(entry: { module?: string; message?: string; level?: string; [key: string]: unknown }): boolean {
  const mod = (entry.module_name ?? entry.module ?? "").toString().toLowerCase();
  const msg = (entry.message ?? "").toString().toLowerCase();
  // Module-based: broker / alpaca / tradier calls
  if (mod.includes("broker") || mod.includes("alpaca") || mod.includes("tradier")) return true;
  // Message-based: bar fetching, database ops, network errors
  if (msg.includes("http") || msg.includes("timeout") || msg.includes("connection")
    || msg.includes("socket") || msg.includes("request") || msg.includes("retry")
    || msg.includes("yfinance") || msg.includes("ssl")
    || msg.includes("get_bars") || msg.includes("get_session_bars")
    || msg.includes("session_bars") || msg.includes("bars for 20")   // "201 bars for 2026-..."
    || msg.includes("get_account") || msg.includes("get_snapshot")
    || msg.includes("circuit breaker") || msg.includes("network")
    || msg.includes("backfill") || msg.includes("database initialised")
    || msg.includes("initialised at /") || msg.includes("synced")
    || msg.includes("alpaca_get_failed") || msg.includes("extended_live")) return true;
  return false;
}

function PnlBadge({ value }: { value?: number }) {
  if (value == null) return <span className="text-ink-muted">—</span>;
  return (
    <span style={{ color: value >= 0 ? "var(--positive)" : "var(--negative)" }}>
      {value >= 0 ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

export function LiveTrading() {
  const [ticker,          setTicker]          = useState("SPY");
  const [tf,              setTf]              = useState("5Min");
  const [period,          setPeriod]          = useState<Period>("1D");
  const [showVwap,        setShowVwap]        = useState(true);
  const [showVwapBands,   setShowVwapBands]   = useState(true);
  const [showOR,          setShowOR]          = useState(true);
  const [showSwings,      setShowSwings]      = useState(true);
  const [showPositionCard,setShowPositionCard]= useState(true);
  // Which scanner ticker is expanded (shows mini charts)
  const [expandedScanner, setExpandedScanner] = useState<string | null>(null);
  // Bot thinking: pause log scroll when user hovers inside the panel
  const [logPaused,     setLogPaused]     = useState(false);
  const logSnapshotRef  = useRef<typeof logs>([]);
  // Bot thinking: active sub-tab ("thinking" = trading decisions, "network" = broker/API)
  const [logTab,        setLogTab]        = useState<"thinking" | "network">("thinking");

  const { status, logs } = useBotStore();

  const { data: bars = [], isLoading: barsLoading } = useQuery({
    queryKey: ["bars", ticker, tf],
    queryFn: () => api.market.bars(ticker, tf, 500),
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

  // Mini chart bars for the expanded scanner ticker (4 timeframes)
  const { data: mini1m  = [] } = useQuery({
    queryKey: ["bars", expandedScanner, "1Min"],
    queryFn:  () => api.market.bars(expandedScanner!, "1Min", 60),
    enabled:  !!expandedScanner,
    refetchInterval: 60_000,
  });
  const { data: mini5m  = [] } = useQuery({
    queryKey: ["bars", expandedScanner, "5Min"],
    queryFn:  () => api.market.bars(expandedScanner!, "5Min", 60),
    enabled:  !!expandedScanner,
    refetchInterval: 60_000,
  });
  const { data: mini15m = [] } = useQuery({
    queryKey: ["bars", expandedScanner, "15Min"],
    queryFn:  () => api.market.bars(expandedScanner!, "15Min", 60),
    enabled:  !!expandedScanner,
    refetchInterval: 60_000,
  });
  const { data: mini1h  = [] } = useQuery({
    queryKey: ["bars", expandedScanner, "1Hour"],
    queryFn:  () => api.market.bars(expandedScanner!, "1Hour", 40),
    enabled:  !!expandedScanner,
    refetchInterval: 60_000,
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

  // Filter bars by selected period
  const visibleBars = useMemo(() => filterByPeriod(bars, period), [bars, period]);

  // Determine sparkline color for scanner ticker (green if positive change, red otherwise)
  const scannerColor = (changePct: number) =>
    changePct >= 0 ? "var(--positive)" : "var(--negative)";

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
            className="flex items-center gap-3 px-3 py-2 border-b text-sm flex-wrap"
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

            {/* Period selector */}
            <div className="flex gap-1">
              {(["1D","5D","1M","3M"] as const).map((p) => (
                <button
                  key={p}
                  className={`btn btn-sm ${period === p ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setPeriod(p)}
                >
                  {p}
                </button>
              ))}
            </div>

            {/* Overlay toggles */}
            {([
              ["VWAP",  showVwap,       setShowVwap],
              ["Bands", showVwapBands,  setShowVwapBands],
              ["OR",    showOR,         setShowOR],
              ["Swings",showSwings,     setShowSwings],
              ["Pos",   showPositionCard, setShowPositionCard],
            ] as [string, boolean, (v: boolean) => void][]).map(([label, val, setter]) => (
              <label key={label} className="flex items-center gap-1 cursor-pointer text-xs"
                     style={{ color: val ? "var(--ink)" : "var(--ink-muted)" }}>
                <input type="checkbox" checked={val}
                       onChange={(e) => setter(e.target.checked)} />
                {label}
              </label>
            ))}

            <div className="flex-1" />
            {barsLoading && <RefreshCw size={13} className="animate-spin text-ink-muted" />}
          </div>

          <TradingChart
            bars={visibleBars}
            trades={tickerTrades}
            showVwap={showVwap}
            showVwapBands={showVwapBands}
            showOR={showOR}
            showSwings={showSwings}
            showPositionCard={showPositionCard}
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
          <div className="overflow-y-auto flex-1">
            {scanner.length === 0 ? (
              <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                No scan results yet — bot scans 9:00–9:25 ET
              </p>
            ) : (
              scanner.map((s) => {
                const isExpanded = expandedScanner === s.ticker;
                const sparkColor = scannerColor(s.change_pct);
                return (
                  <div key={s.ticker}>
                    {/* Ticker row */}
                    <button
                      className="w-full px-3 py-2 flex items-center justify-between hover:bg-muted transition-colors text-left border-b"
                      style={{ borderColor: "var(--border)" }}
                      onClick={() => {
                        setTicker(s.ticker);
                        setExpandedScanner(isExpanded ? null : s.ticker);
                      }}
                    >
                      <div>
                        <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                          {s.ticker}
                        </div>
                        <div className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                          ${s.price.toFixed(2)} · {s.rvol.toFixed(1)}x RVOL
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5">
                        <span
                          className="text-xs num font-medium"
                          style={{ color: sparkColor }}
                        >
                          {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--ink-muted)" }}>
                          {isExpanded ? "▲" : "▼"} charts
                        </span>
                      </div>
                    </button>

                    {/* Expanded mini charts — 4 timeframes */}
                    {isExpanded && (
                      <div
                        className="px-2 py-2 grid grid-cols-2 gap-2 border-b"
                        style={{ borderColor: "var(--border)", background: "var(--surface-raised)" }}
                      >
                        {[
                          { label: "1m",  data: mini1m },
                          { label: "5m",  data: mini5m },
                          { label: "15m", data: mini15m },
                          { label: "1h",  data: mini1h },
                        ].map(({ label, data }) => {
                          const lastClose = data.length ? data[data.length - 1].close : null;
                          const firstClose = data.length ? data[0].close : null;
                          const change = (lastClose && firstClose) ? ((lastClose - firstClose) / firstClose * 100) : null;
                          const c = change != null && change >= 0 ? "var(--positive)" : "var(--negative)";
                          return (
                            <div
                              key={label}
                              className="rounded p-1"
                              style={{ border: "1px solid var(--border)" }}
                            >
                              <div className="flex justify-between items-center mb-0.5">
                                <span className="text-[10px] font-semibold" style={{ color: "var(--ink-muted)" }}>
                                  {label}
                                </span>
                                {change != null && (
                                  <span className="text-[10px] num" style={{ color: c }}>
                                    {change >= 0 ? "+" : ""}{change.toFixed(2)}%
                                  </span>
                                )}
                              </div>
                              <MiniSparkline bars={data} color={change != null && change >= 0 ? "#3fb950" : "#f85149"} />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Bot Focus */}
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
          {/* Header with sub-tabs */}
          {(() => {
            const displayLogs = logPaused ? logSnapshotRef.current : logs;
            const networkLogs  = displayLogs.filter((e) => isNetworkLog(e));
            const thinkingLogs = displayLogs.filter((e) => !isNetworkLog(e));
            const netHasError  = networkLogs.some((e) =>
              (e.level ?? "").toUpperCase() === "ERROR"
            );
            const activeLogs = logTab === "network" ? networkLogs : thinkingLogs;
            return (
              <>
                <div
                  className="border-b flex items-center justify-between"
                  style={{ borderColor: "var(--border)" }}
                >
                  {/* Sub-tabs */}
                  <div className="flex">
                    {(["thinking", "network"] as const).map((tab) => {
                      const isNetwork = tab === "network";
                      const isActive  = logTab === tab;
                      const hasNetErr = isNetwork && netHasError;
                      return (
                        <button
                          key={tab}
                          onClick={() => setLogTab(tab)}
                          className="px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors"
                          style={{
                            borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                            color: hasNetErr
                              ? "var(--negative)"          // network tab red on errors
                              : isActive
                                ? "var(--ink)"
                                : "var(--ink-muted)",
                            background: "none",
                            cursor: "pointer",
                          }}
                        >
                          {tab === "thinking" ? "Thinking" : "Network"}
                          {isNetwork && netHasError && (
                            <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse align-middle" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {logPaused && (
                    <span className="badge badge-blue text-[9px] animate-pulse mr-2">⏸ PAUSED</span>
                  )}
                </div>

                {/* Log feed */}
                <div
                  className="flex-1 overflow-y-auto p-2 flex flex-col gap-1 font-mono text-xs"
                  style={{ maxHeight: 280, cursor: logPaused ? "text" : "default" }}
                  onMouseEnter={() => {
                    logSnapshotRef.current = [...logs];
                    setLogPaused(true);
                  }}
                  onMouseLeave={() => {
                    setLogPaused(false);
                  }}
                >
                  {activeLogs.slice(0, 80).map((entry, i) => {
                    // Visual separator between historical (replayed) and live logs
                    if (isSeparator(entry)) {
                      return (
                        <div key={i} className="flex items-center gap-2 my-1 select-none"
                          style={{ color: "var(--ink-faint)", fontSize: 10 }}>
                          <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
                          <span>previous session</span>
                          <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
                        </div>
                      );
                    }
                    const lvl = (entry.level ?? "INFO").toUpperCase();
                    const color =
                      lvl === "ERROR"   ? "var(--negative)" :
                      lvl === "WARNING" ? "var(--warning)"  :
                      entry.event?.includes("Trade_Signal") ? "var(--positive)" :
                      "var(--ink-muted)";
                    return (
                      <div key={i} style={{ color }}>
                        {entry.ts && (
                          <span
                            className="opacity-60 mr-1 select-none"
                            style={{ color: "var(--ink-muted)", minWidth: "6.5em", display: "inline-block" }}
                          >
                            {entry.ts}
                          </span>
                        )}
                        {entry.event && (
                          <span className="badge badge-blue mr-1">{entry.event}</span>
                        )}
                        {String(entry.message ?? "")}
                      </div>
                    );
                  })}
                  {activeLogs.length === 0 && (
                    <p style={{ color: "var(--ink-muted)" }}>
                      {logs.length === 0 ? "Waiting for bot…" : `No ${logTab} logs yet`}
                    </p>
                  )}
                </div>
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
