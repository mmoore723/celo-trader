/**
 * Performance.tsx — P&L analytics, equity curve, and deep breakdowns.
 */
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar as RBar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell,
} from "recharts";
// Note: BarChart/RBar/Cell still used in analytics sections below
import { api } from "../lib/api";
import { useThemeStore } from "../store/theme";
import { useBotStore } from "../store/bot";
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

// ── Calendar heatmap — monthly + yearly views ─────────────────────────────────
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAYS   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

function pnlColor(pnl: number | undefined, maxAbs: number, dark: boolean): string {
  if (pnl == null) return "transparent";
  if (Math.abs(pnl) < 0.01) return dark ? "#21262d" : "#f0f2f7"; // no trade
  const intensity = Math.min(1, Math.abs(pnl) / (maxAbs || 1));
  if (pnl > 0) {
    // green: low → #1a4731, high → #3fb950 (dark) / #bbf7d0 → #16a34a (light)
    const r = dark ? Math.round(31 + intensity * (80 - 31))   : Math.round(187 - intensity * (187 - 22));
    const g = dark ? Math.round(71 + intensity * (185 - 71))  : Math.round(247 - intensity * (247 - 163));
    const b = dark ? Math.round(49 + intensity * (80 - 49))   : Math.round(208 - intensity * (208 - 74));
    return `rgb(${r},${g},${b})`;
  } else {
    // red: low → #4b1113, high → #f85149 (dark) / #fecaca → #dc2626 (light)
    const r = dark ? Math.round(75 + intensity * (248 - 75))  : Math.round(254 - intensity * (254 - 220));
    const g = dark ? Math.round(17 + intensity * (81 - 17))   : Math.round(202 - intensity * (202 - 38));
    const b = dark ? Math.round(19 + intensity * (73 - 19))   : Math.round(202 - intensity * (202 - 38));
    return `rgb(${r},${g},${b})`;
  }
}

function MonthGrid({
  year, month, pnlMap, maxAbs, dark, tooltip, setTooltip,
}: {
  year: number; month: number; // month 0-based
  pnlMap: Record<string, number>;
  maxAbs: number; dark: boolean;
  tooltip: string | null; setTooltip: (s: string | null) => void;
}) {
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad to full weeks
  while (cells.length % 7 !== 0) cells.push(null);

  return (
    <div>
      <div className="text-xs font-semibold mb-1" style={{ color: "var(--ink-muted)" }}>
        {MONTHS[month]} {year}
      </div>
      {/* Day-of-week header */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2, marginBottom: 2 }}>
        {DAYS.map((d) => (
          <div key={d} style={{ fontSize: 9, color: "var(--ink-faint)", textAlign: "center" }}>{d[0]}</div>
        ))}
      </div>
      {/* Date cells */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2 }}>
        {cells.map((day, i) => {
          if (!day) return <div key={i} />;
          const dateStr = `${year}-${String(month + 1).padStart(2,"0")}-${String(day).padStart(2,"0")}`;
          const pnl = pnlMap[dateStr];
          const bg  = pnlColor(pnl, maxAbs, dark);
          const isWeekend = (firstDay + day - 1) % 7 === 0 || (firstDay + day - 1) % 7 === 6;
          const tipKey = `${dateStr}`;
          return (
            <div
              key={i}
              title={pnl != null ? `${dateStr}: ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}` : dateStr}
              onMouseEnter={() => pnl != null && setTooltip(tipKey)}
              onMouseLeave={() => setTooltip(null)}
              style={{
                height: 28,
                borderRadius: 3,
                background: isWeekend && pnl == null
                  ? (dark ? "#161b22" : "#f8fafc")
                  : bg || (dark ? "#21262d" : "#f0f2f7"),
                display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center",
                cursor: pnl != null ? "default" : "default",
                border: tooltip === tipKey ? "1px solid var(--accent)" : "1px solid transparent",
                position: "relative",
              }}
            >
              <span style={{ fontSize: 9, color: pnl != null ? (dark ? "#e6edf3" : "#1f2937") : "var(--ink-faint)", fontWeight: pnl != null ? 600 : 400 }}>
                {day}
              </span>
              {pnl != null && (
                <span style={{ fontSize: 7, color: dark ? "#e6edf3" : "#1f2937", lineHeight: 1 }}>
                  {pnl >= 0 ? "+" : ""}{pnl >= 100 || pnl <= -100 ? `$${Math.round(pnl)}` : `$${pnl.toFixed(0)}`}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CalendarHeatmap({ daily, dark }: { daily: { date: string; pnl: number }[]; dark: boolean }) {
  const [view, setView]           = useState<"month" | "year">("month");
  const [monthOffset, setMonthOffset] = useState(0); // 0 = current month
  const [tooltip, setTooltip]     = useState<string | null>(null);

  const pnlMap = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of daily) m[d.date] = d.pnl;
    return m;
  }, [daily]);

  const maxAbs = useMemo(() =>
    Math.max(1, ...daily.map((d) => Math.abs(d.pnl))),
  [daily]);

  const now   = new Date();
  const year  = now.getFullYear();

  // Month view target
  const target     = new Date(year, now.getMonth() + monthOffset, 1);
  const tYear      = target.getFullYear();
  const tMonth     = target.getMonth();
  const monthLabel = `${MONTHS[tMonth]} ${tYear}`;

  return (
    <div className="card p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <SectionHeader title="Daily P&L Calendar" />
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex gap-1">
            {(["month", "year"] as const).map((v) => (
              <button
                key={v}
                className={`btn btn-sm ${view === v ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setView(v)}
              >
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>
          {/* Month navigation (month view only) */}
          {view === "month" && (
            <div className="flex items-center gap-1">
              <button className="btn btn-ghost btn-sm" onClick={() => setMonthOffset((o) => o - 1)}>‹</button>
              <span className="text-xs font-semibold" style={{ color: "var(--ink)", minWidth: 80, textAlign: "center" }}>
                {monthLabel}
              </span>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setMonthOffset((o) => Math.min(o + 1, 0))}
                disabled={monthOffset >= 0}
              >›</button>
            </div>
          )}
        </div>
      </div>

      {/* Monthly view */}
      {view === "month" && (
        <MonthGrid
          year={tYear} month={tMonth}
          pnlMap={pnlMap} maxAbs={maxAbs} dark={dark}
          tooltip={tooltip} setTooltip={setTooltip}
        />
      )}

      {/* Yearly view — 3×4 grid of month mini-calendars */}
      {view === "year" && (
        <div>
          <div className="text-xs font-semibold mb-3" style={{ color: "var(--ink-muted)" }}>{year}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20 }}>
            {Array.from({ length: 12 }, (_, m) => (
              <MonthGrid
                key={m}
                year={year} month={m}
                pnlMap={pnlMap} maxAbs={maxAbs} dark={dark}
                tooltip={tooltip} setTooltip={setTooltip}
              />
            ))}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-2 mt-4" style={{ color: "var(--ink-faint)", fontSize: 10 }}>
        <span>Loss</span>
        {[1, 0.6, 0.2].map((i) => (
          <div key={i} style={{ width: 14, height: 14, borderRadius: 2,
            background: pnlColor(-maxAbs * i, maxAbs, dark) }} />
        ))}
        <div style={{ width: 14, height: 14, borderRadius: 2,
          background: dark ? "#21262d" : "#f0f2f7" }} />
        {[0.2, 0.6, 1].map((i) => (
          <div key={i} style={{ width: 14, height: 14, borderRadius: 2,
            background: pnlColor(maxAbs * i, maxAbs, dark) }} />
        ))}
        <span>Profit</span>
      </div>
    </div>
  );
}

export function Performance() {
  const botStatus = useBotStore((s) => s.status);
  const defaultMode: "paper" | "live" = botStatus?.is_paper === false ? "live" : "paper";
  const [mode, setMode] = useState<"paper" | "live">(defaultMode);
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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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

      {/* Daily P&L Calendar */}
      <CalendarHeatmap daily={daily} dark={dark} />

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
