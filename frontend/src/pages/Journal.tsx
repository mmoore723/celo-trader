/**
 * Journal.tsx — Trade journal table with MFE, exit efficiency, and expandable trade detail.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, type Trade } from "../lib/api";
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
 * Expandable efficiency detail panel shown when a trade row is clicked.
 * Uses 4 data points: entry, MAE low, MFE peak, exit — rendered as a bar chart.
 * Explains what "ideal" would have looked like vs what actually happened.
 */
function TradeDetail({ t }: { t: Trade }) {
  const ep  = t.entry_price;
  const xp  = t.exit_price ?? ep;
  const pp  = t.peak_price ?? xp;
  const mp  = t.mae_price  ?? ep;

  // Bar chart comparing key price levels
  const pricePoints = [
    { label: "MAE Low",  value: mp,  color: "var(--negative)" },
    { label: "Entry",    value: ep,  color: "var(--ink-muted)" },
    { label: "Exit",     value: xp,  color: xp >= ep ? "var(--positive)" : "var(--negative)" },
    { label: "MFE Peak", value: pp,  color: "var(--accent)" },
  ].sort((a, b) => a.value - b.value);

  // Narrative: "what should have happened"
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
      <td colSpan={15} style={{ padding: 0 }}>
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

export function Journal() {
  const [mode,        setMode]        = useState<"paper" | "live">("paper");
  const [filter,      setFilter]      = useState<"all" | "open" | "closed">("all");
  const [expandedId,  setExpandedId]  = useState<number | null>(null);
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["trades", mode, filter],
    queryFn: () => api.trades.list(mode, filter),
    refetchInterval: 10_000,
  });

  const trades: Trade[] = data?.trades ?? [];

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
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1">
          {(["paper", "live"] as const).map((m) => (
            <button
              key={m}
              className={`btn btn-sm ${mode === m ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setMode(m)}
            >
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {(["all", "open", "closed"] as const).map((f) => (
            <button
              key={f}
              className={`btn btn-sm ${filter === f ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setFilter(f)}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="flex gap-4 text-sm num" style={{ color: "var(--ink-muted)" }}>
          <span>{data?.total ?? 0} trades</span>
          <span style={{ color: (data?.total_pnl ?? 0) >= 0 ? posColor : negColor }}>
            {(data?.total_pnl ?? 0) >= 0 ? "+" : ""}${Math.abs(data?.total_pnl ?? 0).toFixed(2)} P&L
          </span>
          <span>Win {data?.win_rate ?? 0}%</span>
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          {isLoading ? (
            <PageLoader label="Trade Journal" />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 18 }}></th>  {/* expand toggle */}
                  <th>#</th>
                  <th>Ticker</th>
                  <th>Dir</th>
                  <th>Strategy</th>
                  <th>Entry $</th>
                  <th>Exit $</th>
                  <th>MFE</th>
                  <th>Efficiency</th>
                  <th>Qty</th>
                  <th>P&L</th>
                  <th>Status</th>
                  <th>Exit Reason</th>
                  <th>Entry Time</th>
                  <th>Exit Time</th>
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
                  trades.flatMap((t) => {
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
                        {/* Expand toggle */}
                        <td style={{ paddingRight: 0, color: "var(--ink-faint)" }}>
                          {hasDetail
                            ? isExpanded
                              ? <ChevronDown size={12} />
                              : <ChevronRight size={12} />
                            : null}
                        </td>
                        <td className="num text-xs" style={{ color: "var(--ink-muted)" }}>{t.id}</td>
                        <td className="font-semibold">{t.ticker}</td>
                        <td>
                          <span className={`badge ${t.direction === "long" ? "badge-green" : "badge-red"}`}>
                            {t.direction?.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {t.strategy_id ?? "—"}
                        </td>
                        <td className="num">${t.entry_price.toFixed(2)}</td>
                        <td className="num">
                          {t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}
                        </td>
                        {/* MFE % */}
                        <td className="num text-xs"
                            style={{ color: mfe != null && mfe > 0 ? posColor : "var(--ink-muted)" }}>
                          {mfe != null ? `+${mfe.toFixed(1)}%` : "—"}
                        </td>
                        {/* Exit efficiency % */}
                        <td className="num text-xs" style={{
                          color: eff == null
                            ? "var(--ink-muted)"
                            : eff >= 70 ? posColor
                            : eff >= 40 ? "var(--warning)"
                            : negColor,
                        }}>
                          {eff != null ? `${eff.toFixed(0)}%` : "—"}
                        </td>
                        <td className="num">{t.contracts}</td>
                        <td className="num font-medium"
                            style={{ color: (t.pnl ?? 0) >= 0 ? posColor : negColor }}>
                          {t.pnl != null
                            ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)}`
                            : "—"}
                        </td>
                        <td><StatusBadge status={t.status} /></td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {t.exit_reason ?? "—"}
                        </td>
                        <td className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                          {fmtTime(t.entry_time)}
                        </td>
                        <td className="text-xs num" style={{ color: "var(--ink-muted)" }}>
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
                      // Inline expanded detail row
                      ...(isExpanded && hasDetail ? [<TradeDetail key={`detail-${t.id}`} t={t} />] : []),
                    ];
                  })
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
