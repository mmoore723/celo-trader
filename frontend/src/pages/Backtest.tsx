/**
 * Backtest.tsx — Run historical strategy backtests.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import { api } from "../lib/api";
import { useThemeStore } from "../store/theme";

const TICKERS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "COIN"];

type Direction = "both" | "calls_only" | "puts_only";

const DIRECTION_OPTS: { value: Direction; label: string; desc: string }[] = [
  { value: "both",       label: "Auto",        desc: "Strategy decides: calls on bullish signals, puts on bearish. Simulates the live bot including flip trades." },
  { value: "calls_only", label: "Calls Only",  desc: "Filter: only simulate bullish signals (calls)" },
  { value: "puts_only",  label: "Puts Only",   desc: "Filter: only simulate bearish signals (puts)" },
];

// Default date range: last 3 months
function defaultStart() {
  const d = new Date();
  d.setMonth(d.getMonth() - 3);
  return d.toISOString().slice(0, 10);
}
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export function Backtest() {
  const [ticker,    setTicker]    = useState("SPY");
  const [startDate, setStartDate] = useState(defaultStart());
  const [endDate,   setEndDate]   = useState(todayStr());
  const [capital,   setCapital]   = useState(1000);
  const [direction, setDirection] = useState<Direction>("both");
  const [showTrades, setShowTrades] = useState(true);
  const { theme } = useThemeStore();
  const dark = theme === "dark";

  const { mutate, data: result, isPending, isError, error } = useMutation({
    mutationFn: () => api.backtest.run(ticker, 3, capital, direction, startDate, endDate),
  });

  const gridColor = dark ? "#21262d" : "#f0f2f7";
  const posColor  = dark ? "#3fb950" : "#16a34a";
  const negColor  = dark ? "#f85149" : "#dc2626";
  const tickColor = dark ? "#8b949e" : "#5a6476";

  // Build equity curve from daily_pnl
  let cum = capital;
  const equity = Object.entries(result?.daily_pnl ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, pnl]) => {
      cum += pnl;
      return { date, value: +cum.toFixed(2) };
    });

  return (
    <div className="p-4 flex flex-col gap-4 max-w-3xl">
      {/* Config */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Backtest Configuration
        </h3>
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Ticker</label>
            <select className="select" value={ticker} onChange={(e) => setTicker(e.target.value)}>
              {TICKERS.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Start Date</label>
            <input
              type="date" value={startDate}
              max={endDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input w-36"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>End Date</label>
            <input
              type="date" value={endDate}
              min={startDate} max={todayStr()}
              onChange={(e) => setEndDate(e.target.value)}
              className="input w-36"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Starting capital ($)</label>
            <input
              type="number" min={100} step={100} value={capital}
              onChange={(e) => setCapital(parseFloat(e.target.value))}
              className="input w-32"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Direction</label>
            <div className="flex gap-1">
              {DIRECTION_OPTS.map((opt) => (
                <button
                  key={opt.value}
                  title={opt.desc}
                  className={`btn btn-sm ${direction === opt.value ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setDirection(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <button
            className="btn btn-primary"
            onClick={() => mutate()}
            disabled={isPending}
          >
            <Play size={14} />
            {isPending ? "Running…" : "Run Backtest"}
          </button>
        </div>
      </div>

      {isError && (
        <div className="card p-4" style={{ background: "var(--negative-bg)", borderColor: "var(--negative)" }}>
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            {(error as Error).message}
          </p>
        </div>
      )}

      {result?.error && (
        <div className="card p-4" style={{ background: "var(--negative-bg)", borderColor: "var(--negative)" }}>
          <p className="text-sm" style={{ color: "var(--negative)" }}>{result.error}</p>
        </div>
      )}

      {result && !result.error && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: "Total Return",  value: `${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct.toFixed(1)}%`,
                color: result.total_return_pct >= 0 ? posColor : negColor },
              { label: "Win Rate",      value: `${result.win_rate_pct.toFixed(1)}%` },
              { label: "Total Trades",  value: result.total_trades },
              { label: "Final Balance", value: `$${result.final_balance.toFixed(2)}` },
              { label: "Avg Win",       value: `+$${result.avg_win.toFixed(2)}`,  color: posColor },
              { label: "Avg Loss",      value: `$${result.avg_loss.toFixed(2)}`,  color: negColor },
              { label: "Sharpe",        value: result.sharpe.toFixed(2) },
              { label: "Max Drawdown",  value: `${result.max_drawdown_pct.toFixed(1)}%`, color: negColor },
            ].map((s) => (
              <div key={s.label} className="card px-4 py-3">
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
                <div className="num font-semibold text-lg mt-0.5"
                     style={{ color: s.color ?? "var(--ink)" }}>
                  {s.value}
                </div>
              </div>
            ))}
          </div>

          {/* Call vs Put breakdown (only shown when direction = "both") */}
          {direction === "both" && (result.call_trades ?? 0) + (result.put_trades ?? 0) > 0 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Calls vs Puts
              </h3>
              <div className="grid grid-cols-2 gap-3">
                {[
                  {
                    label: "▲ Calls",
                    trades: result.call_trades ?? 0,
                    wr: result.call_win_rate ?? 0,
                    pnl: result.call_pnl ?? 0,
                    color: posColor,
                  },
                  {
                    label: "▼ Puts",
                    trades: result.put_trades ?? 0,
                    wr: result.put_win_rate ?? 0,
                    pnl: result.put_pnl ?? 0,
                    color: negColor,
                  },
                ].map((row) => (
                  <div key={row.label} className="card px-4 py-3 flex flex-col gap-1">
                    <span className="text-xs font-semibold" style={{ color: row.color }}>{row.label}</span>
                    <div className="flex gap-4 text-xs num">
                      <span style={{ color: "var(--ink-muted)" }}>
                        {row.trades} trades · {row.wr.toFixed(1)}% WR
                      </span>
                      <span style={{ color: row.pnl >= 0 ? posColor : negColor }}>
                        {row.pnl >= 0 ? "+" : ""}${row.pnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Equity curve */}
          {equity.length > 1 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Equity Curve — {ticker} ({startDate} → {endDate})
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={equity}>
                  <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: tickColor }} />
                  <YAxis tick={{ fontSize: 10, fill: tickColor }} />
                  <Tooltip
                    contentStyle={{
                      background: dark ? "#161b22" : "#fff",
                      border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                      borderRadius: 8, fontSize: 12,
                    }}
                    formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "Balance"]}
                  />
                  <ReferenceLine y={capital} stroke={dark ? "#30363d" : "#e2e5ed"} strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="value"
                        stroke={result.total_return_pct >= 0 ? posColor : negColor}
                        strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Per-strategy breakdown */}
          {Object.keys(result.strategy_breakdown ?? {}).length > 0 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Strategy Breakdown
              </h3>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="text-right">Trades</th>
                      <th className="text-right">Win Rate</th>
                      <th className="text-right">P&amp;L</th>
                      <th className="text-right">Avg / Trade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.strategy_breakdown ?? {})
                      .sort(([, a], [, b]) =>
                        (b as { pnl: number }).pnl - (a as { pnl: number }).pnl
                      )
                      .map(([sid, raw]) => {
                        const s = raw as { trades: number; wins: number; win_rate: number; pnl: number };
                        const avg = s.trades > 0 ? s.pnl / s.trades : 0;
                        return (
                          <tr key={sid}>
                            <td className="font-medium text-xs">{sid}</td>
                            <td className="num text-right text-xs">{s.trades}</td>
                            <td className="num text-right text-xs"
                                style={{ color: s.win_rate >= 50 ? posColor : negColor }}>
                              {s.win_rate.toFixed(1)}%
                            </td>
                            <td className="num text-right text-xs font-semibold"
                                style={{ color: s.pnl >= 0 ? posColor : negColor }}>
                              {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
                            </td>
                            <td className="num text-right text-xs"
                                style={{ color: avg >= 0 ? posColor : negColor }}>
                              {avg >= 0 ? "+" : ""}${avg.toFixed(2)}
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Exit reasons */}
          {Object.keys(result.exit_reasons).length > 0 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Exit Reasons
              </h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.exit_reasons).map(([reason, info]) => {
                  const count = typeof info === "object" && info !== null
                    ? (info as { count: number; pnl: number }).count
                    : Number(info);
                  const pnl = typeof info === "object" && info !== null
                    ? (info as { count: number; pnl: number }).pnl
                    : undefined;
                  return (
                    <div key={reason} className="card px-3 py-1.5 text-xs num">
                      <span style={{ color: "var(--ink)" }}>{count}×</span>{" "}
                      <span style={{ color: "var(--ink-muted)" }}>{reason}</span>
                      {pnl !== undefined && (
                        <span style={{ color: pnl >= 0 ? posColor : negColor, marginLeft: 4 }}>
                          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Trade-by-trade table */}
          {result.trades.length > 0 && (
            <div className="card p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                  Trade-by-Trade ({result.trades.length} trades)
                </h3>
                <button
                  className="btn btn-ghost btn-sm text-xs"
                  onClick={() => setShowTrades((v) => !v)}
                >
                  {showTrades ? "Hide" : "Show"}
                </button>
              </div>
              {showTrades && (
                <div className="overflow-x-auto" style={{ maxHeight: 420 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Date</th>
                        <th>Dir</th>
                        <th>Strategy</th>
                        <th className="text-right">Entry $</th>
                        <th className="text-right">Exit $</th>
                        <th className="text-right">P&L</th>
                        <th>Exit Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t, i) => {
                        // Backtester returns plain dicts — field names may vary slightly
                        const raw = t as Record<string, unknown>;
                        const entry  = raw.entry_price as number ?? raw.entry as number ?? 0;
                        const exit_p = raw.exit_price  as number ?? raw.exit  as number ?? 0;
                        const pnl    = raw.pnl         as number ?? raw.realized_pnl as number ?? 0;
                        const dir    = (raw.direction  as string ?? raw.option_type as string ?? "").toLowerCase();
                        const strat  = raw.strategy_id as string ?? raw.strategy as string ?? "—";
                        const reason = raw.exit_reason as string ?? "—";
                        const date   = (raw.entry_time as string ?? raw.date as string ?? "").slice(0, 10);
                        const isLong = dir === "long" || dir === "call";
                        return (
                          <tr key={i}>
                            <td className="num text-xs" style={{ color: "var(--ink-muted)" }}>{i + 1}</td>
                            <td className="text-xs num" style={{ color: "var(--ink-muted)" }}>{date}</td>
                            <td>
                              <span style={{
                                fontSize: 9, fontWeight: 700, padding: "1px 4px", borderRadius: 3,
                                background: isLong ? "rgba(0,200,100,0.15)" : "rgba(255,80,80,0.15)",
                                color: isLong ? posColor : negColor,
                              }}>
                                {(dir || "?").toUpperCase().slice(0, 4)}
                              </span>
                            </td>
                            <td className="text-xs" style={{ color: "var(--ink-muted)" }}>{strat}</td>
                            <td className="num text-right text-xs">${entry.toFixed(2)}</td>
                            <td className="num text-right text-xs">${exit_p.toFixed(2)}</td>
                            <td className="num text-right text-xs font-semibold"
                                style={{ color: pnl >= 0 ? posColor : negColor }}>
                              {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                            </td>
                            <td className="text-xs" style={{ color: "var(--ink-muted)" }}>{reason}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
