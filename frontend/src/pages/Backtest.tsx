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

export function Backtest() {
  const [ticker, setTicker] = useState("SPY");
  const [months, setMonths] = useState(3);
  const [capital, setCapital] = useState(1000);
  const { theme } = useThemeStore();
  const dark = theme === "dark";

  const { mutate, data: result, isPending, isError, error } = useMutation({
    mutationFn: () => api.backtest.run(ticker, months, capital),
  });

  const gridColor = dark ? "#21262d" : "#f0f2f7";
  const posColor  = dark ? "#3fb950" : "#16a34a";
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
            <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Look-back (months)</label>
            <input
              type="number" min={1} max={24} value={months}
              onChange={(e) => setMonths(parseInt(e.target.value))}
              className="input w-28"
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
              { label: "Total Return",     value: `${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct.toFixed(1)}%`,
                color: result.total_return_pct >= 0 ? posColor : dark ? "#f85149" : "#dc2626" },
              { label: "Win Rate",         value: `${result.win_rate_pct.toFixed(1)}%` },
              { label: "Total Trades",     value: result.total_trades },
              { label: "Final Balance",    value: `$${result.final_balance.toFixed(2)}` },
              { label: "Avg Win",          value: `+$${result.avg_win.toFixed(2)}` },
              { label: "Avg Loss",         value: `$${result.avg_loss.toFixed(2)}` },
              { label: "Sharpe",           value: result.sharpe.toFixed(2) },
              { label: "Max Drawdown",     value: `${result.max_drawdown_pct.toFixed(1)}%`,
                color: dark ? "#f85149" : "#dc2626" },
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

          {/* Equity curve */}
          {equity.length > 1 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Equity Curve — {ticker} ({months}mo)
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
                  <Line type="monotone" dataKey="value" stroke={posColor}
                        strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Exit reasons */}
          {Object.keys(result.exit_reasons).length > 0 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                Exit Reasons
              </h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.exit_reasons).map(([reason, count]) => (
                  <div key={reason} className="card px-3 py-1.5 text-xs num">
                    <span style={{ color: "var(--ink)" }}>{String(count)}×</span>{" "}
                    <span style={{ color: "var(--ink-muted)" }}>{reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
