import { strategyName } from "../lib/strategyIdentity.js";
/**
 * Performance.tsx — actionable trading analytics dashboard.
 *
 * Sections (top → bottom):
 *   1. Mode toggle
 *   2. Key stats strip  — P&L, Win%, Profit Factor, Avg Win, Avg Loss, Total Trades
 *   3. Daily P&L bars  — bar per trading day + cumulative equity line
 *   4. Strategy table  — profit factor, avg win/loss, P&L share bar
 *   5. Signal quality  — false signal rate (momentum_dead), exit analysis
 *   6. Ticker table    — per-symbol breakdown
 *   7. Entry hour      — win rate by hour of day
 *   8. Calendar        — monthly heatmap at bottom
 */
import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar as RBar,
  XAxis, YAxis, Tooltip as ChartTooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell,
} from "recharts";
import { X } from "lucide-react";
import { api } from "../lib/api";
import { useThemeStore } from "../store/theme";
import { useBotStore } from "../store/bot";
import { PageLoader } from "../components/PageLoader";
import { Tooltip } from "../components/Tooltip";
import { GLOSSARY } from "../lib/glossary";
import { formatSignedCurrency } from "../lib/money.js";
import { PostMarketReport } from "./DailyBrief";
import { exitReason } from '../lib/strategyIdentity.js';

// ── Exit reason categorisation (frontend only) ────────────────────────────────
type ExitGroup = "target" | "timecap" | "signal" | "stop" | "cutoff" | "other";

function categoriseExit(raw: string): { label: string; group: ExitGroup } {
  const key = (raw || "").split(/[\s(]/)[0];
  const label = exitReason(raw);
  if (/premium_|giveback|stage1_/.test(key)) return {label, group: 'target'};
  if (/time_cap|markout_|selected_test_|timebox_|failed_range_30m/.test(key)) return {label, group: 'timecap'};
  if (/session_/.test(key)) return {label, group: 'cutoff'};
  if (/stop|adverse_|kill_lock/.test(key)) return {label, group: 'stop'};
  if (/momentum|vwap/.test(key)) return {label, group: 'signal'};
  return {label, group: 'other'};
}

const GROUP_COLOR: Record<ExitGroup, string> = {
  target:  "var(--positive)",
  timecap: "#58a6ff",
  cutoff:  "#8b949e",
  signal:  "#f0883e",
  stop:    "var(--negative)",
  other:   "#8b949e",
};

// ── Calendar helpers ──────────────────────────────────────────────────────────
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAYS   = ["S","M","T","W","T","F","S"];

function pnlColor(pnl: number | undefined, maxAbs: number, dark: boolean): string {
  if (pnl == null || Math.abs(pnl) < 0.01) return dark ? "#21262d" : "#f0f2f7";
  const intensity = Math.min(1, Math.abs(pnl) / (maxAbs || 1));
  if (pnl > 0) {
    const r = dark ? Math.round(31  + intensity * 49)  : Math.round(187 - intensity * 165);
    const g = dark ? Math.round(71  + intensity * 114) : Math.round(247 - intensity * 84);
    const b = dark ? Math.round(49  + intensity * 31)  : Math.round(208 - intensity * 134);
    return `rgb(${r},${g},${b})`;
  }
  const r = dark ? Math.round(75  + intensity * 173) : Math.round(254 - intensity * 34);
  const g = dark ? Math.round(17  + intensity * 64)  : Math.round(202 - intensity * 164);
  const b = dark ? Math.round(19  + intensity * 54)  : Math.round(202 - intensity * 164);
  return `rgb(${r},${g},${b})`;
}

function CalendarMonth({
  year, month, pnlMap, maxAbs, dark, onSelect,
}: {
  year: number; month: number; pnlMap: Record<string,number>; maxAbs: number; dark: boolean;
  onSelect: (date: string) => void;
}) {
  const firstDay    = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-muted)", marginBottom: 4 }}>
        {MONTHS[month]} {year}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 1, marginBottom: 2 }}>
        {DAYS.map((d, i) => (
          <div key={i} style={{ fontSize: 8, color: "var(--ink-faint)", textAlign: "center" }}>{d}</div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2 }}>
        {cells.map((day, i) => {
          if (!day) return <div key={i} />;
          const ds  = `${year}-${String(month+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`;
          const pnl = pnlMap[ds];
          return (
            <button key={i} type="button" title={`${pnl != null ? `${pnl>=0?"+":""}$${pnl.toFixed(2)} · ` : ""}Open ${ds} brief`}
              onClick={() => onSelect(ds)}
              style={{
                height: 26, borderRadius: 3,
                background: pnlColor(pnl, maxAbs, dark),
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                border: "none", cursor: "pointer", padding: 0,
              }}
              aria-label={`Open post-market brief for ${ds}`}
            >
              <span style={{ fontSize: 8, color: pnl!=null ? (dark?"#e6edf3":"#1f2937") : "var(--ink-faint)", fontWeight: pnl!=null?600:400 }}>
                {day}
              </span>
              {pnl != null && (
                <span style={{ fontSize: 6.5, color: dark?"#e6edf3":"#1f2937", lineHeight: 1 }}>
                  {pnl>=0?"+":""}{Math.abs(pnl)>=100?`$${Math.round(pnl)}`:`$${pnl.toFixed(0)}`}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Small reusable pieces ──────────────────────────────────────────────────────
function StatCard({ label, value, sub, color }: {
  label: React.ReactNode; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="card px-4 py-3 flex flex-col gap-0.5" style={{ minWidth: 0 }}>
      <span style={{ fontSize: 11, color: "var(--ink-muted)" }}>{label}</span>
      <span style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--ink)", fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
      {sub && <span style={{ fontSize: 10, color: "var(--ink-faint)" }}>{sub}</span>}
    </div>
  );
}

function Hdr({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-3">
      <h3 style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", marginBottom: sub?2:0 }}>{title}</h3>
      {sub && <p style={{ fontSize: 11, color: "var(--ink-muted)" }}>{sub}</p>}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function Performance() {
  const botStatus  = useBotStore((s) => s.status);
  const defaultMode: "paper"|"live" = botStatus?.is_paper===false ? "live" : "paper";
  const [mode, setMode] = useState<"paper"|"live">(defaultMode);
  const [briefDate, setBriefDate] = useState<string | null>(null);
  const { theme } = useThemeStore();
  const dark = theme === "dark";

  const { data: perf, isLoading } = useQuery({
    queryKey: ["performance", mode],
    queryFn:  () => api.trades.performance(mode),
    refetchInterval: 30_000,
  });
  const { data: analytics } = useQuery({
    queryKey: ["analytics", mode],
    queryFn:  () => api.trades.analytics(mode),
    refetchInterval: 60_000,
    retry: false,
  });
  // The nightly evidence review remains a backend process. Performance only
  // consumes its one non-duplicative result: whether each strategy has enough
  // recent closed trades for a human review. P&L and win-rate stay sourced
  // from the performance endpoints above.
  const { data: evidence } = useQuery({
    queryKey: ["strategy-evidence", mode, 30],
    queryFn: () => api.strategyHealth.scorecard(30),
    refetchInterval: 60_000,
    retry: false,
  });

  // ── All useMemo calls before any conditional return (Rules of Hooks) ─────────

  // Exit reason aggregation — merge raw strings into categories
  const exitBreakdown = useMemo(() => {
    const raw = analytics?.by_exit_reason ?? [];
    const merged: Record<string, { label: string; group: ExitGroup; trades: number; total_pnl: number }> = {};
    for (const r of raw) {
      const { label, group } = categoriseExit(r.reason);
      if (!merged[label]) merged[label] = { label, group, trades: 0, total_pnl: 0 };
      merged[label].trades    += r.trades;
      merged[label].total_pnl += r.total_pnl;
    }
    return Object.values(merged)
      .map((m) => ({ ...m, avg_pnl: m.trades > 0 ? m.total_pnl / m.trades : 0 }))
      .sort((a, b) => b.total_pnl - a.total_pnl);
  }, [analytics]);

  // False signal stats: momentum_dead exits
  const falseSigStats = useMemo(() => {
    const total  = analytics?.by_exit_reason?.reduce((s, r) => s + r.trades, 0) ?? 0;
    const deadRow = exitBreakdown.find((e) => e.group === "signal");
    if (!deadRow || !total) return null;
    return {
      count: deadRow.trades,
      pct:   (deadRow.trades / total * 100).toFixed(0),
      total_pnl: deadRow.total_pnl,
      avg_pnl:   deadRow.avg_pnl,
    };
  }, [exitBreakdown, analytics]);

  // P&L share bar width per strategy
  const stratTotalPnl = useMemo(() => {
    const rows = analytics?.by_strategy ?? [];
    const gross = rows.reduce((s, r) => s + (r.total_pnl > 0 ? r.total_pnl : 0), 0);
    return Math.max(gross, 1);
  }, [analytics]);

  // Calendar and every headline metric use the same confirmed bot-trade ledger.
  // Mixing Alpaca portfolio history here with strategy-scoped rows elsewhere
  // made totals disagree whenever the brokerage account contained other P&L.
  const { pnlMap, calMaxAbs } = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of (perf?.daily_summaries ?? [])) m[d.date] = d.pnl;
    const maxAbs = Math.max(1, ...Object.values(m).map(Math.abs));
    return { pnlMap: m, calMaxAbs: maxAbs };
  }, [perf]);

  const { data: briefTrades, isLoading: briefTradesLoading, isError: briefTradesFailed } = useQuery({
    queryKey: ["performance-daily-brief-trades", mode, briefDate],
    queryFn: () => api.trades.list(mode, "all", briefDate!),
    enabled: !!briefDate,
    retry: false,
  });
  const { data: briefScorecard, isLoading: briefScorecardLoading, isError: briefScorecardFailed } = useQuery({
    queryKey: ["performance-daily-brief-scorecard", mode, briefDate],
    queryFn: () => api.strategyHealth.dailyScorecard(mode, briefDate!),
    enabled: !!briefDate,
    retry: false,
  });

  if (isLoading && !perf) return <PageLoader label="Performance" />;

  // Derived colours
  const posColor  = dark ? "#3fb950" : "#16a34a";
  const negColor  = dark ? "#f85149" : "#dc2626";
  const gridColor = dark ? "#21262d" : "#f0f2f7";
  const tickColor = dark ? "#8b949e" : "#5a6476";
  const lineColor = dark ? "#58a6ff" : "#2563eb";

  // Top-level stats
  const winRate    = perf?.win_rate ?? 0;
  const avgWin     = perf?.avg_win ?? 0;
  const avgLoss    = perf?.avg_loss ?? 0;
  const totalTrades= perf?.total_trades ?? 0;
  const streak     = perf?.current_streak ?? 0;
  // Edge ratio: avg win ÷ avg loss (avg_loss is negative)
  const edgeRatio  = avgLoss < 0 ? (avgWin / Math.abs(avgLoss)).toFixed(1) : null;
  const displayPnl = perf?.total_pnl ?? 0;

  const byStrategy = analytics?.by_strategy ?? [];
  const evidenceByStrategy = new Map((evidence?.strategies ?? []).map((row) => [row.strategy_id, row]));
  const byTicker   = analytics?.by_ticker   ?? [];
  const byHour     = analytics?.by_hour     ?? [];
  const now        = new Date();

  return (
    <div className="p-4 flex flex-col gap-4">

      <header>
        <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>Results and evidence</p>
        <h1 className="text-xl font-semibold mt-1" style={{ color: "var(--ink)" }}>Performance</h1>
        <p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Actual trade results, where gains and losses came from, and whether each strategy has enough recent evidence to review responsibly.</p>
      </header>

      {/* ── Mode toggle ───────────────────────────────────────────────────── */}
      <div className="flex gap-2">
        {(["paper","live"] as const).map((m) => (
          <button key={m}
            className={`btn btn-sm ${mode===m ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setMode(m)}>
            {m.charAt(0).toUpperCase()+m.slice(1)} Mode
          </button>
        ))}
      </div>

      {/* ── Key stats strip ───────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">

        {/* Win Rate */}
        <StatCard
          label={<Tooltip text={GLOSSARY["Win Rate"]}>Win Rate</Tooltip>}
          value={`${winRate.toFixed(1)}%`}
          sub={`${totalTrades} trades`}
          color={winRate >= 50 ? posColor : "var(--ink)"}
        />

        {/* Edge Ratio */}
        <StatCard
          label="Edge Ratio"
          value={edgeRatio ? `${edgeRatio}×` : "—"}
          sub={edgeRatio ? `avg win ${edgeRatio}× avg loss` : "no closed trades"}
          color={edgeRatio && Number(edgeRatio) >= 2 ? posColor : "var(--ink)"}
        />

        {/* Total P&L — Alpaca actual if available */}
        <div className="card px-4 py-3 flex flex-col gap-0.5" style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, color: "var(--ink-muted)" }}>Total P&L</span>
            <span style={{
              fontSize: 9, fontWeight: 600, padding: "1px 6px", borderRadius: 99,
              background: "rgba(38,166,154,0.12)",
              color: "#26a69a",
            }}>
              ✓ closed trades
            </span>
          </div>
          <span style={{
            fontSize: 20, fontWeight: 700, fontVariantNumeric: "tabular-nums",
            color: displayPnl >= 0 ? posColor : negColor,
          }}>
            {formatSignedCurrency(displayPnl)}
          </span>
          <span style={{ fontSize: 10, color: "var(--ink-faint)" }}>
            same ledger as the tables below
          </span>
        </div>

        {/* Streak */}
        <StatCard
          label="Streak"
          value={streak > 0 ? `W${streak}` : streak < 0 ? `L${Math.abs(streak)}` : "—"}
          sub={streak > 0 ? "consecutive wins" : streak < 0 ? "consecutive losses" : "break even"}
          color={streak > 0 ? posColor : streak < 0 ? negColor : "var(--ink)"}
        />
      </div>

      {/* ── Calendar heatmap — at top for quick date overview ───────────── */}
      {Object.keys(pnlMap).length > 0 && (
        <div className="card p-4">
          <div className="mb-3 flex items-center gap-2 flex-wrap">
            <div>
              <h3 style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)", marginBottom: 2 }}>Monthly Calendar</h3>
              <p style={{ fontSize: 11, color: "var(--ink-muted)" }}>Daily P&L colour intensity</p>
            </div>
            <span style={{ fontSize: 10, color: "var(--ink-faint)" }}>Select a day to open its final brief</span>
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(220px,1fr))", gap:24 }}>
            {[1, 0].map((offset) => {
              const d = new Date(now.getFullYear(), now.getMonth() - offset, 1);
              return (
                <CalendarMonth key={offset}
                  year={d.getFullYear()} month={d.getMonth()}
                  pnlMap={pnlMap} maxAbs={calMaxAbs} dark={dark} onSelect={setBriefDate} />
              );
            })}
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:6, marginTop:12,
            color:"var(--ink-faint)", fontSize:10 }}>
            <span>Loss</span>
            {[1, 0.5, 0.1].map((i) => (
              <div key={i} style={{ width:12, height:12, borderRadius:2,
                background: pnlColor(-calMaxAbs*i, calMaxAbs, dark) }} />
            ))}
            <div style={{ width:12, height:12, borderRadius:2, background:dark?"#21262d":"#f0f2f7" }} />
            {[0.1, 0.5, 1].map((i) => (
              <div key={i} style={{ width:12, height:12, borderRadius:2,
                background: pnlColor(calMaxAbs*i, calMaxAbs, dark) }} />
            ))}
            <span>Profit</span>
          </div>
        </div>
      )}

      {/* ── Strategy + exits side by side ────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(360px,1fr))", gap: 12, alignItems: "start" }}>
      {byStrategy.length > 0 && (
        <div className="card p-4">
          <Hdr title="Strategy Performance"
               sub="Results and 30-day evidence status in one place. Review-ready means enough trades to inspect—not proof of future profitability." />
          <div className="overflow-x-auto">
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th className="text-right">Trades</th>
                  <th className="text-right"><Tooltip text={GLOSSARY["Win Rate"]}>Win%</Tooltip></th>
                  <th className="text-right"><Tooltip text={GLOSSARY["Profit Factor"]}>PF</Tooltip></th>
                  <th className="text-right">Avg Win</th>
                  <th className="text-right">Avg Loss</th>
                  <th className="text-right">Total P&L</th>
                  <th>Evidence</th>
                  <th style={{ width: 80 }}>P&L Share</th>
                </tr>
              </thead>
              <tbody>
                {byStrategy.map((s) => {
                  const sharePct = s.total_pnl > 0
                    ? Math.min(100, (s.total_pnl / stratTotalPnl) * 100)
                    : 0;
                  const pf = s.profit_factor ?? 0;
                  const strategyEvidence = evidenceByStrategy.get(s.strategy_id);
                  const evidenceTrades = strategyEvidence?.closed_trades ?? 0;
                  const reviewReady = strategyEvidence?.sample_status === "review_ready";
                  return (
                    <tr key={s.strategy_id}>
                      <td style={{ fontWeight: 600 }}>{strategyName(s.strategy_id)}</td>
                      <td className="num text-right">{s.trades}</td>
                      <td className="num text-right"
                          style={{ color: s.win_rate>=50 ? posColor : s.win_rate>=40 ? "var(--ink)" : negColor }}>
                        {s.win_rate.toFixed(0)}%
                      </td>
                      <td className="num text-right"
                          style={{ fontWeight:600, color: pf>=3 ? posColor : pf>=1.5 ? "var(--ink)" : negColor }}>
                        {pf > 0 ? pf.toFixed(1) : "—"}
                      </td>
                      <td className="num text-right" style={{ color: posColor }}>
                        {s.avg_win > 0 ? `+$${s.avg_win.toFixed(2)}` : "—"}
                      </td>
                      <td className="num text-right" style={{ color: negColor }}>
                        {s.avg_loss < 0 ? `$${s.avg_loss.toFixed(2)}` : "—"}
                      </td>
                      <td className="num text-right" style={{ fontWeight:600,
                          color: s.total_pnl>=0 ? posColor : negColor }}>
                        {s.total_pnl>=0?"+":""}${s.total_pnl.toFixed(2)}
                      </td>
                      <td>
                        <span className={`badge ${reviewReady ? "badge-green" : "badge-yellow"}`}>
                          {reviewReady ? "READY TO REVIEW" : "COLLECTING"}
                        </span>
                        <div style={{ marginTop: 3, fontSize: 10, color: "var(--ink-faint)", whiteSpace: "nowrap" }}>
                          {evidenceTrades}/{evidence?.minimum_review_trades ?? 20} recent closed trades
                        </div>
                      </td>
                      <td style={{ paddingLeft: 8 }}>
                        {sharePct > 0 && (
                          <div style={{ height: 8, borderRadius: 4,
                            background: dark?"#21262d":"#f0f2f7", overflow:"hidden" }}>
                            <div style={{ height:"100%", width:`${sharePct}%`,
                              background: posColor, borderRadius:4 }} />
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Signal quality / false signal analysis ────────────────────────── */}
      {exitBreakdown.length > 0 && (
        <div className="card p-4">
          <Hdr title="Exit Analysis"
               sub="What's closing your trades and what each type earns on average." />

          {/* False signal callout */}
          {falseSigStats && (
            <div style={{
              background: dark ? "rgba(240,136,62,0.08)" : "rgba(240,136,62,0.06)",
              border: "1px solid rgba(240,136,62,0.25)",
              borderRadius: 8, padding: "10px 14px", marginBottom: 16,
              display:"flex", alignItems:"center", gap:12, flexWrap:"wrap",
            }}>
              <span style={{ fontSize: 20 }}>⚠️</span>
              <div>
                <p style={{ fontSize: 12, fontWeight:600, color:"#f0883e" }}>
                  {falseSigStats.pct}% of trades exit as Dead Momentum — {falseSigStats.count} entries
                  where volume faded immediately
                </p>
                <p style={{ fontSize: 11, color:"var(--ink-muted)", marginTop:2 }}>
                  Avg loss per false signal: ${Math.abs(falseSigStats.avg_pnl).toFixed(2)} ·
                  Total drag: ${Math.abs(falseSigStats.total_pnl).toFixed(2)} ·
                  These are controlled (small losses) but signal quality can be improved —
                  see strategy breakdown above to find which strategies generate the most.
                </p>
              </div>
            </div>
          )}

          {/* Exit breakdown table */}
          <div className="overflow-x-auto">
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Exit Type</th>
                  <th className="text-right">Count</th>
                  <th className="text-right">% Trades</th>
                  <th className="text-right">Total P&L</th>
                  <th className="text-right">Avg / Trade</th>
                  <th style={{ width: 100 }}>Contribution</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const totalExits = exitBreakdown.reduce((s, r) => s + r.trades, 0);
                  const maxAbs = Math.max(1, ...exitBreakdown.map((r) => Math.abs(r.total_pnl)));
                  return exitBreakdown.map((r) => {
                    const barPct = Math.abs(r.total_pnl) / maxAbs * 100;
                    const col    = GROUP_COLOR[r.group];
                    return (
                      <tr key={r.label}>
                        <td>
                          <span style={{ display:"inline-block", width:8, height:8,
                            borderRadius:"50%", background:col, marginRight:6 }} />
                          {r.label}
                        </td>
                        <td className="num text-right">{r.trades}</td>
                        <td className="num text-right" style={{ color:"var(--ink-muted)" }}>
                          {(r.trades / totalExits * 100).toFixed(0)}%
                        </td>
                        <td className="num text-right font-semibold"
                            style={{ color: r.total_pnl>=0 ? posColor : negColor }}>
                          {r.total_pnl>=0?"+":""}${r.total_pnl.toFixed(2)}
                        </td>
                        <td className="num text-right"
                            style={{ color: r.avg_pnl>=0 ? posColor : negColor }}>
                          {r.avg_pnl>=0?"+":""}${r.avg_pnl.toFixed(2)}
                        </td>
                        <td style={{ paddingLeft: 8 }}>
                          <div style={{ height: 8, borderRadius:4,
                            background: dark?"#21262d":"#f0f2f7", overflow:"hidden" }}>
                            <div style={{ height:"100%", width:`${barPct}%`,
                              background: col, borderRadius:4, opacity: r.total_pnl<0 ? 0.6 : 1 }} />
                          </div>
                        </td>
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </div>
      {briefDate && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" style={{ background: "rgba(15, 23, 42, 0.68)" }} role="dialog" aria-modal="true" aria-label={`Post-market brief for ${briefDate}`} onMouseDown={event => { if (event.target === event.currentTarget) setBriefDate(null); }}>
          <div className="card w-full max-w-4xl max-h-[90vh] overflow-y-auto p-4" style={{ background: "var(--surface)" }}>
            <div className="flex items-center justify-between gap-3 mb-4">
              <div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>Post-market daily brief</p><h2 className="text-lg font-semibold">{briefDate}</h2></div>
              <button type="button" className="btn btn-ghost" onClick={() => setBriefDate(null)} aria-label="Close daily brief"><X size={18} /></button>
            </div>
            {(briefTradesLoading || briefScorecardLoading) ? <PageLoader label="Daily brief" /> : (briefTradesFailed || briefScorecardFailed) ? <div role="alert" className="p-6 text-sm" style={{ color: "var(--negative)" }}>This daily brief could not be loaded.</div> : <PostMarketReport trades={briefTrades?.trades ?? []} scorecard={briefScorecard} scorecardLoading={false} scorecardFailed={false} finalized reportDate={briefDate} />}
          </div>
        </div>
      )}
      {/* ── Ticker + Hour side by side ────────────────────────────────────── */}
      <div style={{ display:"grid", gap:12, gridTemplateColumns:"1fr 1fr" }}>

        {/* Ticker table */}
        {byTicker.length > 0 && (
          <div className="card p-4">
            <Hdr title="By Ticker" />
            <div className="overflow-x-auto">
              <table className="data-table" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="text-right">T</th>
                    <th className="text-right">Win%</th>
                    <th className="text-right">Avg W</th>
                    <th className="text-right">Avg L</th>
                    <th className="text-right">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {byTicker.map((t) => (
                    <tr key={t.ticker}>
                      <td style={{ fontWeight:600 }}>{t.ticker}</td>
                      <td className="num text-right">{t.trades}</td>
                      <td className="num text-right"
                          style={{ color: t.win_rate>=50 ? posColor : t.win_rate>=40 ? "var(--ink)" : negColor }}>
                        {t.win_rate.toFixed(0)}%
                      </td>
                      <td className="num text-right" style={{ color: posColor }}>
                        {t.avg_win > 0 ? `+$${t.avg_win.toFixed(0)}` : "—"}
                      </td>
                      <td className="num text-right" style={{ color: negColor }}>
                        {t.avg_loss < 0 ? `$${t.avg_loss.toFixed(0)}` : "—"}
                      </td>
                      <td className="num text-right font-semibold"
                          style={{ color: t.total_pnl>=0 ? posColor : negColor }}>
                        {t.total_pnl>=0?"+":""}${t.total_pnl.toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Entry hour chart */}
        {byHour.length > 0 && (
          <div className="card p-4">
            <Hdr title="Win Rate by Entry Hour (ET)"
                 sub="When are entries most effective?" />
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={byHour} margin={{ top:0, right:4, left:-24, bottom:0 }}>
                <CartesianGrid stroke={gridColor} strokeDasharray="3 3" />
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: tickColor }} />
                <YAxis domain={[0,100]} tick={{ fontSize: 9, fill: tickColor }}
                       tickFormatter={(v) => `${v}%`} />
                <ChartTooltip
                  formatter={(v: unknown, n: unknown) => [
                    n==="win_rate" ? `${(v as number).toFixed(1)}%` : `$${(v as number).toFixed(2)}`,
                    n==="win_rate" ? "Win Rate" : "Avg P&L",
                  ]}
                  contentStyle={{ background: dark?"#161b22":"#fff",
                    border: `1px solid ${dark?"#30363d":"#e2e5ed"}`, borderRadius:8, fontSize:12 }}
                />
                <ReferenceLine y={50} stroke={dark?"#30363d":"#e2e5ed"} strokeDasharray="4 2"
                  label={{ value:"50%", position:"right", fontSize:9, fill:tickColor }} />
                <RBar dataKey="win_rate" radius={[3,3,0,0]} maxBarSize={32}>
                  {byHour.map((h, i) => (
                    <Cell key={i} fill={h.win_rate>=50 ? posColor : h.win_rate>=40 ? lineColor : negColor} />
                  ))}
                </RBar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>


    </div>
  );
}
