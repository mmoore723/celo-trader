/**
 * Performance.tsx — P&L analytics, equity curve, and deep breakdowns.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar as RBar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell,
} from "recharts";
import { api } from "../lib/api";
import { useThemeStore } from "../store/theme";
import { PageLoader } from "../components/PageLoader";

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card px-4 py-3 flex flex-col gap-0.5">
      <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</span>
      <span className="num text-xl font-semibold" style={{ color: "var(--ink)" }}>{value}</span>
      {sub && <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{sub}</span>}
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>{title}</h3>
  );
}

export function Performance() {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const { theme } = useThemeStore();
  const dark = theme === "dark";

  const { data: perf, isLoading } = useQuery({
    queryKey: ["performance", mode],
    queryFn: () => api.trades.performance(mode),
    refetchInterval: 30_000,
  });

  const { data: analytics } = useQuery({
    queryKey: ["analytics", mode],
    queryFn: () => api.trades.analytics(mode),
    refetchInterval: 60_000,
    retry: false,
  });

  if (isLoading && !perf) return <PageLoader label="Performance" />;

  const daily      = perf?.daily_summaries ?? [];
  const gridColor  = dark ? "#21262d" : "#f0f2f7";
  const posColor   = dark ? "#3fb950" : "#16a34a";
  const negColor   = dark ? "#f85149" : "#dc2626";
  const tickColor  = dark ? "#8b949e" : "#5a6476";
  const accentColor = dark ? "#58a6ff" : "#2563eb";

  // Cumulative equity curve
  let cum = 0;
  const equity = daily.map((d) => {
    cum += d.pnl;
    return { date: d.date.slice(5), pnl: d.pnl, equity: +cum.toFixed(2) };
  });

  // ── Analytics-derived data ──────────────────────────────────────────────────
  const byStrategy = analytics?.by_strategy ?? [];
  const byHour     = analytics?.by_hour ?? [];
  const byTicker   = analytics?.by_ticker ?? [];
  const byExit     = analytics?.by_exit_reason ?? [];

  // MFE vs Exit comparison chart
  const mfeVsExit = analytics
    ? [
        { name: "Avg MFE",  value: analytics.avg_mfe_pct,  fill: accentColor },
        { name: "Avg Exit", value: analytics.avg_exit_pct, fill: posColor },
      ]
    : [];

  return (
    <div className="p-4 flex flex-col gap-4">
      {/* Mode toggle */}
      <div className="flex items-center gap-2">
        {(["paper", "live"] as const).map((m) => (
          <button
            key={m}
            className={`btn btn-sm ${mode === m ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setMode(m)}
          >
            {m.charAt(0).toUpperCase() + m.slice(1)} Mode
          </button>
        ))}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-3">
        <StatCard
          label="Total P&L"
          value={`${(perf?.total_pnl ?? 0) >= 0 ? "+" : ""}$${Math.abs(perf?.total_pnl ?? 0).toFixed(2)}`}
          sub={`${perf?.total_trades ?? 0} trades`}
        />
        <StatCard
          label="Win Rate"
          value={`${perf?.win_rate ?? 0}%`}
          sub={`Streak: ${perf?.current_streak ?? 0}`}
        />
        <StatCard
          label="Avg Win"
          value={`+$${(perf?.avg_win ?? 0).toFixed(2)}`}
        />
        <StatCard
          label="Avg Loss"
          value={`$${(perf?.avg_loss ?? 0).toFixed(2)}`}
        />
        <StatCard
          label="Best Day"
          value={`+$${(perf?.best_day ?? 0).toFixed(2)}`}
        />
        <StatCard
          label="Worst Day"
          value={`$${(perf?.worst_day ?? 0).toFixed(2)}`}
        />
        {analytics && (
          <>
            <StatCard
              label="Avg MFE"
              value={`+${analytics.avg_mfe_pct.toFixed(1)}%`}
              sub="avg peak per trade"
            />
            <StatCard
              label="Exit Efficiency"
              value={`${analytics.avg_exit_efficiency_pct.toFixed(0)}%`}
              sub="of move captured"
            />
          </>
        )}
      </div>

      {/* Equity curve */}
      <div className="card p-4">
        <SectionHeader title="Cumulative P&L" />
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={equity}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={posColor} stopOpacity={0.3} />
                <stop offset="95%" stopColor={posColor} stopOpacity={0}   />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: tickColor }} />
            <YAxis tick={{ fontSize: 10, fill: tickColor }} />
            <Tooltip
              contentStyle={{
                background: dark ? "#161b22" : "#fff",
                border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                borderRadius: 8, fontSize: 12,
              }}
              formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "Equity"]}
            />
            <ReferenceLine y={0} stroke={dark ? "#30363d" : "#e2e5ed"} />
            <Area
              type="monotone" dataKey="equity"
              stroke={posColor} strokeWidth={2}
              fill="url(#eqGrad)" dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Daily P&L bars */}
      <div className="card p-4">
        <SectionHeader title="Daily P&L" />
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={equity}>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: tickColor }} />
            <YAxis tick={{ fontSize: 10, fill: tickColor }} />
            <Tooltip
              contentStyle={{
                background: dark ? "#161b22" : "#fff",
                border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                borderRadius: 8, fontSize: 12,
              }}
              formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "P&L"]}
            />
            <ReferenceLine y={0} stroke={dark ? "#30363d" : "#e2e5ed"} />
            <RBar dataKey="pnl" radius={[3, 3, 0, 0]}>
              {equity.map((d, i) => (
                <Cell key={i} fill={d.pnl >= 0 ? posColor : negColor} />
              ))}
            </RBar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* ── Analytics sections (only when we have data) ───────────────────── */}
      {analytics && (
        <>
          {/* MFE vs Exit comparison */}
          {(analytics.avg_mfe_pct > 0 || analytics.avg_exit_pct !== 0) && (
            <div className="card p-4">
              <SectionHeader title="Avg MFE vs Avg Exit (% move from entry)" />
              <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
                MFE is how far the option moved in your favor on average. Exit shows what you actually
                captured. The gap is money consistently left on the table.
                Exit efficiency: <strong>{analytics.avg_exit_efficiency_pct.toFixed(0)}%</strong> of the available move captured.
              </p>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={mfeVsExit} layout="vertical"
                          margin={{ top: 0, right: 20, left: 60, bottom: 0 }}>
                  <XAxis type="number" tick={{ fontSize: 10, fill: tickColor }}
                         tickFormatter={(v) => `${v.toFixed(1)}%`} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: tickColor }} />
                  <Tooltip
                    formatter={(v: unknown) => [`${(v as number).toFixed(1)}%`, ""]}
                    contentStyle={{
                      background: dark ? "#161b22" : "#fff",
                      border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                      borderRadius: 8, fontSize: 12,
                    }}
                  />
                  <RBar dataKey="value" radius={[0, 4, 4, 0]}>
                    {mfeVsExit.map((d, i) => <Cell key={i} fill={d.fill} />)}
                  </RBar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Win rate by strategy */}
          {byStrategy.length > 0 && (
            <div className="card p-4">
              <SectionHeader title="Win Rate by Strategy" />
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="text-right">Trades</th>
                      <th className="text-right">Win Rate</th>
                      <th className="text-right">Total P&L</th>
                      <th className="text-right">Avg MFE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byStrategy.map((s) => (
                      <tr key={s.strategy_id}>
                        <td className="font-medium text-xs">{s.strategy_id}</td>
                        <td className="num text-right text-xs">{s.trades}</td>
                        <td className="num text-right text-xs"
                            style={{ color: s.win_rate >= 50 ? posColor : negColor }}>
                          {s.win_rate.toFixed(1)}%
                        </td>
                        <td className="num text-right text-xs font-semibold"
                            style={{ color: s.total_pnl >= 0 ? posColor : negColor }}>
                          {s.total_pnl >= 0 ? "+" : ""}${s.total_pnl.toFixed(2)}
                        </td>
                        <td className="num text-right text-xs"
                            style={{ color: s.avg_mfe_pct > 0 ? posColor : "var(--ink-muted)" }}>
                          {s.avg_mfe_pct > 0 ? `+${s.avg_mfe_pct.toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Win rate by hour and by ticker side by side */}
          {(byHour.length > 0 || byTicker.length > 0) && (
            <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 1fr" }}>
              {/* By hour */}
              {byHour.length > 0 && (
                <div className="card p-4">
                  <SectionHeader title="Win Rate by Hour (ET)" />
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={byHour} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
                      <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
                      <XAxis dataKey="label" tick={{ fontSize: 10, fill: tickColor }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: tickColor }}
                             tickFormatter={(v) => `${v}%`} />
                      <Tooltip
                        formatter={(v: unknown, name: unknown) => [
                          name === "win_rate" ? `${(v as number).toFixed(1)}%` : String(v),
                          name === "win_rate" ? "Win Rate" : "Avg P&L",
                        ]}
                        contentStyle={{
                          background: dark ? "#161b22" : "#fff",
                          border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                          borderRadius: 8, fontSize: 12,
                        }}
                      />
                      <RBar dataKey="win_rate" radius={[3, 3, 0, 0]}>
                        {byHour.map((h, i) => (
                          <Cell key={i} fill={h.win_rate >= 50 ? posColor : negColor} />
                        ))}
                      </RBar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* By ticker */}
              {byTicker.length > 0 && (
                <div className="card p-4">
                  <SectionHeader title="P&L by Ticker" />
                  <div className="overflow-x-auto">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th className="text-right">Trades</th>
                          <th className="text-right">Win %</th>
                          <th className="text-right">P&L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {byTicker.map((t) => (
                          <tr key={t.ticker}>
                            <td className="font-semibold text-xs">{t.ticker}</td>
                            <td className="num text-right text-xs">{t.trades}</td>
                            <td className="num text-right text-xs"
                                style={{ color: t.win_rate >= 50 ? posColor : negColor }}>
                              {t.win_rate.toFixed(1)}%
                            </td>
                            <td className="num text-right text-xs font-medium"
                                style={{ color: t.total_pnl >= 0 ? posColor : negColor }}>
                              {t.total_pnl >= 0 ? "+" : ""}${t.total_pnl.toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* P&L by exit reason */}
          {byExit.length > 0 && (
            <div className="card p-4">
              <SectionHeader title="P&L by Exit Reason" />
              <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
                Tells you which exit type is costing or making the most. Negative avg P&L on a reason
                means those exits are not working — consider adjusting that logic.
              </p>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Exit Reason</th>
                      <th className="text-right">Trades</th>
                      <th className="text-right">Total P&L</th>
                      <th className="text-right">Avg / Trade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byExit
                      .slice()
                      .sort((a, b) => b.total_pnl - a.total_pnl)
                      .map((r) => (
                        <tr key={r.reason}>
                          <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                            {r.reason}
                          </td>
                          <td className="num text-right text-xs">{r.trades}</td>
                          <td className="num text-right text-xs font-semibold"
                              style={{ color: r.total_pnl >= 0 ? posColor : negColor }}>
                            {r.total_pnl >= 0 ? "+" : ""}${r.total_pnl.toFixed(2)}
                          </td>
                          <td className="num text-right text-xs"
                              style={{ color: r.avg_pnl >= 0 ? posColor : negColor }}>
                            {r.avg_pnl >= 0 ? "+" : ""}${r.avg_pnl.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
