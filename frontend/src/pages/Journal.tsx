/**
 * Journal.tsx — Trade journal table with MFE, exit efficiency, and expandable trade detail.
 *              Includes Reconcile tab comparing bot DB records against actual Alpaca fills.
 */
import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from "recharts";
import { ChevronDown, ChevronRight, Download, AlertTriangle, CheckCircle } from "lucide-react";
import {
  api, type Trade, type ReconcileResponse, type ReconcileRow,
  type BrokerOrderFlowResponse,
} from "../lib/api";
import { TradeChartModal as ChartModal } from "../components/charts/TradeChartModal";
import { useBotStore } from "../store/bot";
import { PageLoader } from "../components/PageLoader";

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${status === "open" ? "badge-blue" : "badge-green"}`}>
      {status.toUpperCase()}
    </span>
  );
}

/** Compact time formatter: "06/26 09:45" */
function fmtTime(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

/** Trading-day inputs must follow New York, not the browser's UTC day. */
function todayEt(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** Format duration between two ISO strings as "Xm" or "Xh Ym" */
function fmtDuration(entry?: string, exit?: string): string {
  if (!entry || !exit) return "—";
  const mins = Math.round((new Date(exit).getTime() - new Date(entry).getTime()) / 60_000);
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

/**
 * Expandable efficiency detail panel — shows full raw exit reason, not the normalized short label.
 */
function TradeDetail({ t, onViewChart }: { t: Trade; onViewChart: () => void }) {
  const ep  = t.entry_price;
  const xp  = t.exit_price ?? ep;
  const pp  = t.peak_price ?? xp;
  const mp  = t.mae_price  ?? ep;

  const pricePoints = [
    { label: "MAE Low",  value: mp,  color: "var(--negative)" },
    { label: "Entry",    value: ep,  color: "var(--ink-muted)" },
    { label: "Exit",     value: xp,  color: xp >= ep ? "var(--positive)" : "var(--negative)" },
    { label: "MFE Peak", value: pp,  color: "var(--accent)" },
  ].sort((a, b) => a.value - b.value);

  const eff  = t.exit_efficiency_pct;
  const mfe  = t.mfe_pct;
  const mae  = t.mae_pct;
  const pnl  = t.pnl ?? 0;
  const qty  = t.contracts ?? 1;

  let narrative = "";
  if (mfe != null && mfe > 0 && eff != null) {
    const idealPnl = (pp - ep) * qty * 100;
    const leftOn   = idealPnl - Math.max(0, pnl);
    narrative = eff >= 90
      ? `Near-perfect exit — captured ${eff.toFixed(0)}% of the ${mfe.toFixed(1)}% move.`
      : eff >= 60
      ? `Decent exit — captured ${eff.toFixed(0)}% of the ${mfe.toFixed(1)}% move. ` +
        `Exiting at the peak ($${pp.toFixed(2)}) would have added ~$${leftOn.toFixed(0)}.`
      : `Left money on the table — only ${eff.toFixed(0)}% of the ${mfe.toFixed(1)}% move captured. ` +
        `Peak was $${pp.toFixed(2)}; ideal exit would have been +$${idealPnl.toFixed(0)} ` +
        `instead of ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}.`;
    if (mae != null && mae < -5) {
      narrative += ` Trade dipped to $${mp.toFixed(2)} (${mae.toFixed(1)}%) before recovering — worth reviewing stop placement.`;
    }
  } else if (pnl <= 0) {
    narrative = mae != null
      ? `Loss: option reached a low of $${mp.toFixed(2)} (${(mae ?? 0).toFixed(1)}%) before being stopped. No MFE data recorded.`
      : "Loss with no MFE/MAE data (pre-tracking trade).";
  } else {
    narrative = "MFE data not available for this trade (recorded before peak-price tracking was added).";
  }

  return (
    <tr>
      <td colSpan={16} style={{ padding: 0 }}>
        <div
          className="px-6 py-3 flex gap-6 items-start"
          style={{ background: "var(--surface-raised)", borderBottom: "1px solid var(--border)" }}
        >
          {/* Bar chart */}
          {/* FIX 2026-07-31: real crash — this sat in a flex row (siblings:
              stats grid, button, narrative) with no fixed width of its own,
              inside a horizontally-scrollable table (overflow-x: auto).
              ResponsiveContainer measures its parent via ResizeObserver on
              every layout pass; with no stable width to converge on, that
              measurement can feed back into itself indefinitely — recharts
              uses redux internally, and the observed crash (React error
              #185, stack trace through react-redux's notifyNestedSubs /
              redux-toolkit) is exactly that failure signature. This chart
              is always a small fixed decoration (never needs to grow), so
              a fixed pixel width sidesteps the ResizeObserver loop
              entirely instead of trying to tune around it. */}
          {t.peak_price != null && (
            <div style={{ width: 200, height: 80 }}>
              <BarChart width={200} height={80} data={pricePoints} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                  <XAxis dataKey="label" tick={{ fontSize: 9, fill: "var(--ink-muted)" }} />
                  <YAxis
                    domain={[
                      Math.min(mp, ep) * 0.97,
                      Math.max(pp, xp) * 1.03
                    ]}
                    tick={{ fontSize: 9, fill: "var(--ink-muted)" }}
                    tickFormatter={(v) => `$${v.toFixed(2)}`}
                  />
                  <Tooltip
                    formatter={(v: unknown) => [`$${(v as number).toFixed(3)}`, ""]}
                    contentStyle={{
                      background: "var(--card-bg)", border: "1px solid var(--border)",
                      borderRadius: 6, fontSize: 11,
                    }}
                  />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {pricePoints.map((p, i) => (
                      <Cell key={i} fill={p.color} />
                    ))}
                  </Bar>
                </BarChart>
            </div>
          )}

          {/* Stats grid */}
          <div className="flex flex-col gap-1 text-xs" style={{ color: "var(--ink-muted)", minWidth: 180 }}>
            <div className="flex gap-4">
              <span>MFE: <strong style={{ color: "var(--positive)" }}>
                {mfe != null ? `+${mfe.toFixed(1)}%` : "—"}
              </strong></span>
              <span>MAE: <strong style={{ color: "var(--negative)" }}>
                {mae != null ? `${mae.toFixed(1)}%` : "—"}
              </strong></span>
            </div>
            <div>Efficiency: <strong style={{
              color: eff != null
                ? eff >= 70 ? "var(--positive)" : eff >= 40 ? "var(--warning)" : "var(--negative)"
                : "var(--ink-muted)",
            }}>
              {eff != null ? `${eff.toFixed(0)}%` : "—"}
            </strong></div>
            <div>Hold time: <strong style={{ color: "var(--ink)" }}>
              {fmtDuration(t.entry_time, t.exit_time)}
            </strong></div>
            {/* Full raw exit reason — not normalized — so user sees the real detail */}
            <div>Exit reason: <strong style={{ color: "var(--ink)", wordBreak: "break-all" }}>
              {t.exit_reason ?? "—"}
            </strong></div>
          </div>

          {/* View on Chart button */}
          <button
            onClick={onViewChart}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 12px", borderRadius: 6, cursor: "pointer",
              background: "rgba(167,139,250,0.10)", border: "1px solid rgba(167,139,250,0.35)",
              color: "#a78bfa", fontSize: 11, fontWeight: 600, width: "fit-content",
            }}
          >
            ⏪ View on Chart
          </button>

          {/* Narrative + post-trade recap */}
          <div className="text-xs flex-1" style={{ color: "var(--ink-muted)", lineHeight: 1.5, display: "flex", flexDirection: "column", gap: 8 }}>
            <p style={{ margin: 0 }}>{narrative}</p>
            {/* Post-trade recap — auto-generated by position_manager on close */}
            {t.recap && (
              <div style={{
                background: "var(--surface)", borderRadius: 8,
                border: "1px solid var(--border)", padding: "8px 10px",
              }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "var(--ink-muted)",
                              textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 4 }}>
                  📋 Trade Recap
                </div>
                <p style={{ margin: 0, fontSize: 11, color: "var(--ink)", lineHeight: 1.55 }}>
                  {t.recap}
                </p>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

// ── Reconcile tab ──────────────────────────────────────────────────────────────

function humanStage(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function OrderFlowTab({ mode }: { mode: "paper" | "live" }) {
  const [date, setDate] = useState(todayEt);
  const { data, isLoading, refetch } = useQuery<BrokerOrderFlowResponse>({
    queryKey: ["broker-order-flow", mode, date],
    queryFn: () => api.trades.orderFlow(mode, date),
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
  });
  const summary = data?.summary;
  const metrics = [
    ["Sent", summary?.attempts ?? 0],
    ["Accepted", summary?.acknowledged ?? 0],
    ["Filled", summary?.filled ?? 0],
    ["Failed", summary?.rejected_or_failed ?? 0],
    ["Active issues", summary?.active_issues ?? 0],
  ] as const;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <input type="date" className="input input-sm" value={date}
          onChange={(e) => setDate(e.target.value)} />
        <button className="btn btn-ghost btn-sm" onClick={() => refetch()}>Refresh</button>
        <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{data?.scope_note}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {metrics.map(([label, value]) => (
          <div className="card px-4 py-3" key={label}>
            <div className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</div>
            <div className="text-xl font-semibold num" style={{
              color: label === "Active issues" && value > 0 ? "var(--negative)" : "var(--ink)",
            }}>{value}</div>
          </div>
        ))}
      </div>
      {(summary?.active_issues ?? 0) > 0 && (
        <div className="card px-4 py-3 flex items-center gap-2"
          style={{ borderColor: "var(--negative)", color: "var(--negative)" }}>
          <AlertTriangle size={16} /> One or more Alpaca order lifecycles need attention.
        </div>
      )}
      {isLoading ? <PageLoader label="Alpaca Order Flow" /> : (
        <div className="flex flex-col gap-3">
          {(data?.attempts ?? []).length === 0 ? (
            <div className="card p-8 text-center" style={{ color: "var(--ink-muted)" }}>
              No Alpaca order attempts for {date}.
            </div>
          ) : data!.attempts.map((attempt) => (
            <div className="card p-4" key={attempt.attempt_id}
              style={attempt.active_issue ? { borderColor: "var(--negative)" } : {}}>
              <div className="flex justify-between gap-4 flex-wrap">
                <div>
                  <div className="font-semibold">
                    {attempt.ticker || "Order"} · {attempt.position_intent?.replaceAll("_", " ") || attempt.side}
                  </div>
                  <div className="text-xs" style={{ color: "var(--ink-muted)" }}>
                    {attempt.contract_symbol || "Contract not selected"} · requested {attempt.requested_qty ?? "—"} · {fmtTime(attempt.started_at)}
                  </div>
                </div>
                <div className="text-right">
                  <span className={`badge ${attempt.active_issue ? "badge-red" : attempt.filled_qty ? "badge-green" : "badge-blue"}`}>
                    {humanStage(attempt.final_event)}
                  </span>
                  {attempt.linked_trade_id && <div className="text-xs mt-1">Trade #{attempt.linked_trade_id}</div>}
                </div>
              </div>
              <div className="flex gap-2 flex-wrap mt-3">
                {attempt.events.map((event) => (
                  <div key={event.id} title={event.message || ""} className="text-xs px-2 py-1"
                    style={{
                      border: "1px solid var(--border)", borderRadius: 6,
                      color: event.is_issue ? "var(--negative)" : "var(--ink-muted)",
                    }}>
                    {humanStage(event.event_type)}{event.status ? ` · ${event.status}` : ""}
                  </div>
                ))}
              </div>
              {(attempt.issue_message || attempt.fill_price != null) && (
                <div className="text-xs mt-3" style={{
                  color: attempt.issue_message ? "var(--negative)" : "var(--ink-muted)",
                }}>
                  {attempt.issue_message || `Filled ${attempt.filled_qty} @ $${attempt.fill_price?.toFixed(2)}`}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function fmt$(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}$${Math.abs(v).toFixed(decimals)}`;
}

function fmtPx(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toFixed(2)}`;
}

function ReconcileTab() {
  // Default to today in YYYY-MM-DD
  const todayStr = todayEt();
  const [date, setDate] = useState<string>(todayStr);

  const { data, isLoading, refetch } = useQuery<ReconcileResponse>({
    queryKey: ["reconcile", date],
    queryFn: () => api.trades.reconcile(date),
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });

  const posColor = "var(--positive)";
  const negColor = "var(--negative)";
  const gapColor = "var(--warning)";

  const equityGap = data?.equity_gap ?? null;
  const bigGap    = equityGap != null && Math.abs(equityGap) > 10;
  const brokerLabel = data?.broker_provider === "tradier" ? "Tradier" : "Alpaca";

  return (
    <div className="flex flex-col gap-4">
      {/* Date picker + refresh */}
      <div className="flex items-center gap-3">
        <input
          type="date"
          className="input input-sm"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ fontSize: 13, padding: "3px 8px", height: 30 }}
        />
        <button className="btn btn-ghost btn-sm" onClick={() => refetch()}>Refresh</button>
      </div>

      {isLoading ? (
        <PageLoader label="Reconcile" />
      ) : !data ? (
        <p style={{ color: "var(--ink-muted)" }}>No data returned.</p>
      ) : (
        <>
          {/* ── Equity summary banner ───────────────────────────────────────── */}
          <div
            className="card flex flex-wrap gap-6 px-5 py-3 items-center"
            style={{
              borderColor: bigGap ? "var(--warning)" : "var(--border)",
              borderWidth: bigGap ? 2 : 1,
            }}
          >
            {bigGap && (
              <div className="flex items-center gap-2" style={{ color: gapColor }}>
                <AlertTriangle size={16} />
                <span className="text-sm font-semibold">
                  Equity gap detected — bot P&L and {brokerLabel} account differ by {fmt$(equityGap)}
                </span>
              </div>
            )}
            {!bigGap && equityGap != null && (
              <div className="flex items-center gap-2" style={{ color: posColor }}>
                <CheckCircle size={16} />
                <span className="text-sm font-semibold">P&L looks accurate (gap &lt; $10)</span>
              </div>
            )}
            <div className="flex flex-wrap gap-5 text-sm num ml-auto">
              <div className="flex flex-col items-end">
                <span style={{ fontSize: 10, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Day Start</span>
                <span className="font-semibold">
                  {data.day_start_balance != null ? `$${data.day_start_balance.toFixed(2)}` : "—"}
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span style={{ fontSize: 10, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{brokerLabel} Equity</span>
                <span className="font-semibold">
                  {data.alpaca_equity != null ? `$${data.alpaca_equity.toFixed(2)}` : "—"}
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span style={{ fontSize: 10, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Bot P&L</span>
                <span className="font-semibold"
                      style={{ color: data.bot_session_pnl >= 0 ? posColor : negColor }}>
                  {fmt$(data.bot_session_pnl)}
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span style={{ fontSize: 10, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{brokerLabel} P&L</span>
                <span className="font-semibold"
                      style={{ color: (data.alpaca_session_pnl ?? 0) >= 0 ? posColor : negColor }}>
                  {fmt$(data.alpaca_session_pnl)}
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span style={{ fontSize: 10, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Gap</span>
                <span className="font-semibold"
                      style={{ color: bigGap ? gapColor : "var(--ink-muted)" }}>
                  {fmt$(equityGap)}
                </span>
              </div>
            </div>
          </div>

          {/* ── Per-trade reconcile table ───────────────────────────────────── */}
          <div className="card overflow-hidden">
            <div style={{ padding: "8px 16px 6px", borderBottom: "1px solid var(--border)", fontSize: 12, fontWeight: 600, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Trade-level comparison
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Contract</th>
                    <th>Qty</th>
                    <th>Strategy</th>
                    <th>Status</th>
                    <th>Bot Entry</th>
                    <th>Bot Exit</th>
                    <th>Bot P&L</th>
                    <th>{brokerLabel} Entry</th>
                    <th>{brokerLabel} Exit</th>
                    <th>{brokerLabel} P&L</th>
                    <th>Gap</th>
                  </tr>
                </thead>
                <tbody>
                  {data.trades.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="text-center py-6"
                          style={{ color: "var(--ink-muted)" }}>
                        No trades on {data.date}
                      </td>
                    </tr>
                  ) : (
                    data.trades.map((row: ReconcileRow, i: number) => {
                      // Open positions have nothing to gap-check yet (no exit
                      // fill exists on either side) — 2026-07-28: these used to
                      // be excluded from this endpoint entirely, which made a
                      // real open position's entry fill show up in the scary
                      // "Unmatched Alpaca fills" list below instead of here.
                      const isOpen = row.status === "open";
                      const gapBig = row.has_gap;
                      const bpnl   = row.bot_pnl   ?? 0;
                      const apnl   = row.alpaca_pnl ?? 0;
                      const gap    = row.pnl_gap;
                      return (
                        <tr key={i} style={gapBig ? { background: "color-mix(in srgb, var(--warning) 6%, transparent)" } : {}}>
                          <td className="text-xs" style={{ fontFamily: "monospace", maxWidth: 160, wordBreak: "break-all" }}>
                            {row.contract_symbol ?? "—"}
                          </td>
                          <td className="num">{row.contracts ?? "—"}</td>
                          <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                            {strategyLabel(row.strategy_id)}
                          </td>
                          <td>
                            <span className={`badge ${isOpen ? "badge-blue" : "badge-green"}`}>
                              {isOpen ? "OPEN" : "CLOSED"}
                            </span>
                          </td>
                          <td className="num">{fmtPx(row.bot_entry)}</td>
                          <td className="num">{isOpen ? "—" : fmtPx(row.bot_exit)}</td>
                          <td className="num font-medium"
                              style={{ color: isOpen ? "var(--ink-muted)" : (bpnl >= 0 ? posColor : negColor) }}>
                            {isOpen ? "—" : fmt$(row.bot_pnl)}
                          </td>
                          <td className="num">{fmtPx(row.alpaca_entry)}</td>
                          <td className="num">{isOpen ? "—" : fmtPx(row.alpaca_exit)}</td>
                          <td className="num font-medium"
                              style={{ color: isOpen ? "var(--ink-muted)" : (apnl >= 0 ? posColor : negColor) }}>
                            {isOpen ? "—" : fmt$(row.alpaca_pnl)}
                          </td>
                          <td className="num font-semibold"
                              style={{ color: gapBig ? gapColor : "var(--ink-muted)" }}>
                            {isOpen || gap == null
                              ? "—"
                              : `${gap >= 0 ? "+" : ""}$${Math.abs(gap).toFixed(2)}`}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Unmatched Alpaca orders ─────────────────────────────────────── */}
          {data.unmatched_alpaca_orders.length > 0 && (
            <div className="card overflow-hidden">
              <div style={{ padding: "8px 16px 6px", borderBottom: "1px solid var(--border)", fontSize: 12, fontWeight: 600, color: "var(--warning)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Unmatched {brokerLabel} fills ({data.unmatched_alpaca_orders.length})
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="data-table" style={{ fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>Fill Price</th>
                      <th>Filled At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.unmatched_alpaca_orders.map((o, i) => (
                      <tr key={i}>
                        <td className="text-xs" style={{ fontFamily: "monospace" }}>{o.symbol}</td>
                        <td>
                          <span className={`badge ${o.side === "buy" ? "badge-green" : "badge-red"}`}>
                            {o.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="num">{o.filled_qty}</td>
                        <td className="num">{fmtPx(o.filled_avg_price)}</td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {o.filled_at ? fmtTime(o.filled_at) : "—"}
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

type DateWindow = "today" | "week" | "month" | "custom" | "all";

// Values stay as stable strategy IDs for filtering; labels are written for people.
const STRATEGY_LABELS: Record<string, string> = {
  V2_ORB_PULLBACK: "TSLA Opening-Range Pullback",
  V2_SPY_TREND_CONT: "SPY Trend Continuation",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
  V2_SPY_AFTERNOON_FVG: "SPY Afternoon Fair Value Gap",
  V2_FAILED_OR_BREAK_VWAP_REVERSION: "SPY Failed-Range Recovery",
};
const ALL_STRATEGIES = Object.keys(STRATEGY_LABELS);
const strategyLabel = (strategyId?: string | null) => strategyId
  ? (STRATEGY_LABELS[strategyId] ?? `Retired historical strategy (${strategyId})`)
  : "—";

/** Export the visible trades as a CSV download. */
function exportCsv(trades: Trade[], mode: string) {
  const headers = [
    "id","ticker","direction","strategy","option_type",
    "contracts","entry_price","exit_price",
    "mfe_pct","mae_pct","exit_efficiency_pct",
    "pnl","status","exit_reason","entry_time","exit_time",
  ];
  const rows = trades.map((t) => [
    t.id, t.ticker, t.direction, t.strategy_id ?? "",
    t.option_type ?? "", t.contracts,
    t.entry_price, t.exit_price ?? "",
    t.mfe_pct ?? "", t.mae_pct ?? "", t.exit_efficiency_pct ?? "",
    t.pnl ?? "", t.status,
    (t.exit_reason ?? "").replace(/,/g, ";"),   // escape commas in reason
    t.entry_time ?? "", t.exit_time ?? "",
  ]);
  const csv = [headers, ...rows].map((r) => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `celo_trades_${mode}_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function Journal() {
  const botStatus = useBotStore((s) => s.status);
  const defaultMode: "paper" | "live" = botStatus?.is_paper === false ? "live" : "paper";

  const [mainTab, setMainTab] = useState<"journal" | "order-flow" | "reconcile">("journal");

  const [mode,        setMode]        = useState<"paper" | "live">(defaultMode);
  const [filter,      setFilter]      = useState<"all" | "open" | "closed">("all");
  const [dateWindow,  setDateWindow]  = useState<DateWindow>("all");
  const [customFrom,  setCustomFrom]  = useState<string>("");
  const [stratFilter, setStratFilter] = useState<string>("all");  // strategy filter
  const [expandedId,  setExpandedId]  = useState<number | null>(null);
  const [replayTrade, setReplayTrade] = useState<Trade | null>(null);
  const [page,        setPage]        = useState(0);
  const PAGE_SIZE = 20;
  const qc = useQueryClient();

  // Reset to page 0 whenever any filter changes
  useEffect(() => { setPage(0); }, [mode, filter, dateWindow, customFrom, stratFilter]);

  const { data, isLoading } = useQuery({
    queryKey: ["trades", mode, filter],
    queryFn: () => api.trades.list(mode, filter),
    refetchInterval: 10_000,
  });

  const allTrades: Trade[] = data?.trades ?? [];

  // ── Client-side date filter ─────────────────────────────────────────────────
  const trades = allTrades.filter((t) => {
    // Date filter
    if (t.entry_time) {
      const entry = new Date(t.entry_time);
      const now   = new Date();
      if (dateWindow === "today" && entry.toDateString() !== now.toDateString()) return false;
      if (dateWindow === "week") {
        const cut = new Date(now); cut.setDate(now.getDate() - 7);
        if (entry < cut) return false;
      }
      if (dateWindow === "month") {
        const cut = new Date(now); cut.setMonth(now.getMonth() - 1);
        if (entry < cut) return false;
      }
      if (dateWindow === "custom" && customFrom && entry < new Date(customFrom)) return false;
    }
    // Strategy filter
    if (stratFilter !== "all" && t.strategy_id !== stratFilter) return false;
    return true;
  });

  const pageCount   = Math.max(1, Math.ceil(trades.length / PAGE_SIZE));
  const safePage    = Math.min(page, pageCount - 1);
  const pageTrades  = trades.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  const tradePnl = (t: Trade): number | null => {
    if (t.pnl != null) return t.pnl;
    const live = botStatus?.open_positions?.[String(t.id)];
    if (!live || live.current_option_price == null || t.entry_price == null) return null;
    return (live.current_option_price - t.entry_price) * (t.contracts ?? 0) * 100;
  };
  const filteredPnl     = trades.reduce((s, t) => s + (tradePnl(t) ?? 0), 0);
  const filteredWins    = trades.filter((t) => (tradePnl(t) ?? 0) > 0).length;
  const filteredWinRate = trades.length > 0
    ? ((filteredWins / trades.length) * 100).toFixed(1)
    : "0.0";

  async function close(id: number) {
    await api.bot.closeTrade(id);
    qc.invalidateQueries({ queryKey: ["trades"] });
  }

  function toggleExpand(id: number) {
    setExpandedId(prev => prev === id ? null : id);
  }

  const posColor = "var(--positive)";
  const negColor = "var(--negative)";

  return (
    <>
    <div className="p-4 flex flex-col gap-4">
      {/* Top-level tab switcher */}
      <div className="flex gap-1">
        <button
          className={`btn btn-sm ${mainTab === "journal" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setMainTab("journal")}
        >
          Journal
        </button>
        <button
          className={`btn btn-sm ${mainTab === "order-flow" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setMainTab("order-flow")}
        >
          Alpaca Order Flow
        </button>
        <button
          className={`btn btn-sm ${mainTab === "reconcile" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setMainTab("reconcile")}
        >
          Reconcile
        </button>
      </div>

      {/* Reconcile tab */}
      {mainTab === "reconcile" && <ReconcileTab />}
      {mainTab === "order-flow" && <OrderFlowTab mode={mode} />}

      {/* Journal tab — hidden when reconcile is active */}
      {mainTab === "journal" && (
      <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="card px-4 py-3">
          <div className="text-xs" style={{ color: "var(--ink-muted)" }}>Day Starting Balance</div>
          <div className="num font-semibold">${(botStatus?.day_start_balance ?? 0).toFixed(2)}</div>
        </div>
        <div className="card px-4 py-3">
          <div className="text-xs" style={{ color: "var(--ink-muted)" }}>Current Equity</div>
          <div className="num font-semibold">${(botStatus?.account_balance ?? 0).toFixed(2)}</div>
        </div>
        <div className="card px-4 py-3">
          <div className="text-xs" style={{ color: "var(--ink-muted)" }}>Live Session P&amp;L</div>
          <div className="num font-semibold" style={{ color: (botStatus?.session_pnl ?? 0) >= 0 ? posColor : negColor }}>
            {(botStatus?.session_pnl ?? 0) >= 0 ? "+" : ""}${(botStatus?.session_pnl ?? 0).toFixed(2)}
          </div>
        </div>
      </div>
      {/* Controls */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Paper / Live */}
          <div className="flex gap-1">
            {(["paper", "live"] as const).map((m) => (
              <button key={m}
                className={`btn btn-sm ${mode === m ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setMode(m)}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
          {/* Open / Closed / All */}
          <div className="flex gap-1">
            {(["all", "open", "closed"] as const).map((f) => (
              <button key={f}
                className={`btn btn-sm ${filter === f ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setFilter(f)}>
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          {/* Date window */}
          <div className="flex gap-1 flex-wrap">
            {([
              { key: "today", label: "Today"  },
              { key: "week",  label: "7 Days"  },
              { key: "month", label: "30 Days" },
              { key: "all",   label: "All"     },
              { key: "custom",label: "From…"   },
            ] as { key: DateWindow; label: string }[]).map(({ key, label }) => (
              <button key={key}
                className={`btn btn-sm ${dateWindow === key ? "btn-accent" : "btn-ghost"}`}
                onClick={() => setDateWindow(key)}>
                {label}
              </button>
            ))}
            {dateWindow === "custom" && (
              <input
                type="date"
                className="input input-sm"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                style={{ fontSize: 12, padding: "2px 6px", height: 28 }}
              />
            )}
          </div>
          {/* Strategy filter */}
          <select
            className="select"
            value={stratFilter}
            onChange={(e) => setStratFilter(e.target.value)}
            style={{ fontSize: 12, padding: "2px 8px", height: 28 }}
          >
            <option value="all">All Strategies</option>
            {ALL_STRATEGIES.map((s) => (
              <option key={s} value={s}>{STRATEGY_LABELS[s]}</option>
            ))}
          </select>

          {/* CSV export — exports whatever is currently visible */}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => exportCsv(trades, mode)}
            title="Export visible trades as CSV"
            style={{ display: "flex", alignItems: "center", gap: 4 }}
          >
            <Download size={13} />
            <span className="hidden sm:inline">Export</span>
          </button>
        </div>
        {/* Summary row */}
        <div className="flex gap-4 text-sm num" style={{ color: "var(--ink-muted)" }}>
          <span>{trades.length} trades</span>
          <span style={{ color: filteredPnl >= 0 ? posColor : negColor }}>
            {filteredPnl >= 0 ? "+" : ""}${Math.abs(filteredPnl).toFixed(2)} P&L
          </span>
          <span>Win {filteredWinRate}%</span>
          {stratFilter !== "all" && (
            <span style={{ color: "var(--accent)", fontSize: 11 }}>({stratFilter})</span>
          )}
          {dateWindow !== "all" && (
            <span style={{ color: "var(--accent)", fontSize: 11 }}>
              ({dateWindow === "custom" && customFrom
                ? `from ${customFrom}`
                : dateWindow === "today" ? "today"
                : dateWindow === "week"  ? "last 7 days"
                : "last 30 days"})
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden" style={{ overflowX: "auto" }}>
        <div className="overflow-x-auto">
          {isLoading ? (
            <PageLoader label="Trade Journal" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 18 }}></th>
                  <th className="hidden sm:table-cell">#</th>
                  <th>Ticker</th>
                  <th>Dir</th>
                  <th className="hidden sm:table-cell">Strategy</th>
                  <th>Entry $</th>
                  <th>Exit $</th>
                  <th className="hidden md:table-cell">MFE</th>
                  <th className="hidden md:table-cell">Efficiency</th>
                  <th className="hidden sm:table-cell">Qty</th>
                  <th>P&L</th>
                  <th className="hidden sm:table-cell">Status</th>
                  <th className="hidden lg:table-cell">Exit Reason</th>
                  <th className="hidden lg:table-cell">Entry Time</th>
                  <th className="hidden lg:table-cell">Exit Time</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr>
                    <td colSpan={16} className="text-center py-10"
                        style={{ color: "var(--ink-muted)" }}>
                      No trades found
                    </td>
                  </tr>
                ) : (
                  pageTrades.flatMap((t) => {
                    const isExpanded = expandedId === t.id;
                    const hasDetail  = t.status === "closed" && t.entry_price != null;
                    const eff        = t.exit_efficiency_pct;
                    const mfe        = t.mfe_pct;
                    const displayedPnl = tradePnl(t);

                    return [
                      <tr
                        key={t.id}
                        style={{ cursor: hasDetail ? "pointer" : "default" }}
                        onClick={() => hasDetail && toggleExpand(t.id)}
                      >
                        <td style={{ paddingRight: 0, color: "var(--ink-faint)" }}>
                          {hasDetail
                            ? isExpanded
                              ? <ChevronDown size={12} />
                              : <ChevronRight size={12} />
                            : null}
                        </td>
                        <td className="num text-xs hidden sm:table-cell" style={{ color: "var(--ink-muted)" }}>{t.id}</td>
                        <td className="font-semibold">{t.ticker}</td>
                        <td>
                          <span className={`badge ${t.direction === "long" ? "badge-green" : "badge-red"}`}>
                            {t.direction?.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-xs hidden sm:table-cell" style={{ color: "var(--ink-muted)" }}>
                          {strategyLabel(t.strategy_id)}
                        </td>
                        <td className="num">${t.entry_price.toFixed(2)}</td>
                        <td className="num">
                          {t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}
                        </td>
                        <td className="num text-xs hidden md:table-cell"
                            style={{ color: mfe != null && mfe > 0 ? posColor : "var(--ink-muted)" }}>
                          {mfe != null ? `+${mfe.toFixed(1)}%` : "—"}
                        </td>
                        <td className="num text-xs hidden md:table-cell" style={{
                          color: eff == null
                            ? "var(--ink-muted)"
                            : eff >= 70 ? posColor
                            : eff >= 40 ? "var(--warning)"
                            : negColor,
                        }}>
                          {eff != null ? `${eff.toFixed(0)}%` : "—"}
                        </td>
                        <td className="num hidden sm:table-cell">{t.contracts}</td>
                        <td className="num font-medium"
                            style={{ color: (displayedPnl ?? 0) >= 0 ? posColor : negColor }}>
                          {displayedPnl != null
                            ? `${displayedPnl >= 0 ? "+" : ""}$${displayedPnl.toFixed(2)}${t.status === "open" ? " live" : ""}`
                            : "—"}
                        </td>
                        <td className="hidden sm:table-cell"><StatusBadge status={t.status} /></td>
                        {/* Full raw exit reason in table */}
                        <td className="text-xs hidden lg:table-cell"
                            style={{ color: "var(--ink-muted)", maxWidth: 200, wordBreak: "break-word" }}>
                          {t.exit_reason ?? "—"}
                        </td>
                        <td className="text-xs num hidden lg:table-cell" style={{ color: "var(--ink-muted)" }}>
                          {fmtTime(t.entry_time)}
                        </td>
                        <td className="text-xs num hidden lg:table-cell" style={{ color: "var(--ink-muted)" }}>
                          {fmtTime(t.exit_time)}
                        </td>
                        <td onClick={(e) => e.stopPropagation()}>
                          {t.status === "open" && (
                            <button
                              className="btn btn-ghost btn-sm text-xs"
                              style={{ color: "var(--negative)" }}
                              onClick={() => close(t.id)}
                            >
                              Close
                            </button>
                          )}
                        </td>
                      </tr>,
                      ...(isExpanded && hasDetail ? [<TradeDetail key={`detail-${t.id}`} t={t} onViewChart={() => setReplayTrade(t)} />] : []),
                    ];
                  })
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination bar — only shown when there's more than one page */}
        {pageCount > 1 && (
          <div
            className="flex items-center justify-between px-4 py-2"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <button
              className="btn btn-ghost btn-sm"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
            >
              ← Prev
            </button>
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
              Page {safePage + 1} of {pageCount}
              <span className="ml-2" style={{ color: "var(--ink-faint)" }}>
                ({safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, trades.length)} of {trades.length})
              </span>
            </span>
            <button
              className="btn btn-ghost btn-sm"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
            >
              Next →
            </button>
          </div>
        )}
      </div>
      </div>
      )}
    </div>

    {/* Replay chart modal — opened from "View on Chart" in trade detail */}
    {replayTrade && (
      <ChartModal
        open
        onClose={() => setReplayTrade(null)}
        ticker={replayTrade.ticker}
        mode="replay"
        trade={replayTrade}
      />
    )}
    </>
  );
}
