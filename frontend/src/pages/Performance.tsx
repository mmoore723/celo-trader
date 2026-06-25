/**
 * Performance.tsx — P&L analytics, daily breakdown, equity curve.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar as RBar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
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

export function Performance() {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const { theme } = useThemeStore();
  const dark = theme === "dark";

  const { data: perf, isLoading } = useQuery({
    queryKey: ["performance", mode],
    queryFn: () => api.trades.performance(mode),
    refetchInterval: 30_000,
  });

  if (isLoading) return <PageLoader label="Performance" />;

  const daily = perf?.daily_summaries ?? [];

  // Cumulative equity curve
  let cum = 0;
  const equity = daily.map((d) => {
    cum += d.pnl;
    return { date: d.date, pnl: d.pnl, equity: +cum.toFixed(2) };
  });

  const gridColor = dark ? "#21262d" : "#f0f2f7";
  const posColor  = dark ? "#3fb950" : "#16a34a";

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
      </div>

      {/* Equity curve */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Cumulative P&L
        </h3>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={equity}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={posColor} stopOpacity={0.3} />
                <stop offset="95%" stopColor={posColor} stopOpacity={0}   />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: dark ? "#8b949e" : "#5a6476" }} />
            <YAxis tick={{ fontSize: 10, fill: dark ? "#8b949e" : "#5a6476" }} />
            <Tooltip
              contentStyle={{
                background: dark ? "#161b22" : "#fff",
                border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "Equity"]}
            />
            <ReferenceLine y={0} stroke={dark ? "#30363d" : "#e2e5ed"} />
            <Area
              type="monotone"
              dataKey="equity"
              stroke={posColor}
              strokeWidth={2}
              fill="url(#eqGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Daily P&L bars */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
          Daily P&L
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={daily}>
            <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: dark ? "#8b949e" : "#5a6476" }} />
            <YAxis tick={{ fontSize: 10, fill: dark ? "#8b949e" : "#5a6476" }} />
            <Tooltip
              contentStyle={{
                background: dark ? "#161b22" : "#fff",
                border: `1px solid ${dark ? "#30363d" : "#e2e5ed"}`,
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, "P&L"]}
            />
            <ReferenceLine y={0} stroke={dark ? "#30363d" : "#e2e5ed"} />
            <RBar
              dataKey="pnl"
              radius={[3, 3, 0, 0]}
              fill={posColor}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
