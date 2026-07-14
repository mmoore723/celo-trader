/**
 * Journal.tsx — Trade journal table with MFE, exit efficiency, and expandable trade detail.
 */
import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { api, type Trade } from "../lib/api";
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
function TradeDetail({ t }: { t: Trade }) {
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
          {t.peak_price != null && (
            <div style={{ minWidth: 200, height: 80 }}>
              <ResponsiveContainer width="100%" height={80}>
                <BarChart data={pricePoints} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
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
              </ResponsiveContainer>
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

          {/* Narrative */}
          <p className="text-xs flex-1" style={{ color: "var(--ink-muted)", lineHeight: 1.5 }}>
            {narrative}
          </p>
        </div>
      </td>
    </tr>
  );
}

type DateWindow = "today" | "week" | "month" | "custom" | "all";

// All known strategy IDs (for the filter dropdown)
const ALL_STRATEGIES = ["FVG", "IFVG", "INST_ORB", "VWAP_PB", "MID_BRK", "AFT_REV", "TREND_CONT"];

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

  const [mode,        setMode]        = useState<"paper" | "live">(defaultMode);
  const [filter,      setFilter]      = useState<"all" | "open" | "closed">("all");
  const [dateWindow,  setDateWindow]  = useState<DateWindow>("all");
  const [customFrom,  setCustomFrom]  = useState<string>("");
  const [stratFilter, setStratFilter] = useState<string>("all");  // strategy filter
  const [expandedId,  setExpandedId]  = useState<number | null>(null);
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

  const filteredPnl     = trades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const filteredWins    = trades.filter((t) => (t.pnl ?? 0) > 0).length;
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
    <div className="p-4 flex flex-col gap-4">
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
              <option key={s} value={s}>{s}</option>
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
                          {t.strategy_id ?? "—"}
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
                            style={{ color: (t.pnl ?? 0) >= 0 ? posColor : negColor }}>
                          {t.pnl != null
                            ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)}`
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
                      ...(isExpanded && hasDetail ? [<TradeDetail key={`detail-${t.id}`} t={t} />] : []),
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
  );
}
