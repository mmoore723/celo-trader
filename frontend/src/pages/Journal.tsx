/**
 * Journal.tsx — Trade journal table with filters.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Trade } from "../lib/api";

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${status === "open" ? "badge-blue" : "badge-green"}`}>
      {status.toUpperCase()}
    </span>
  );
}

export function Journal() {
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
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
          <span
            style={{ color: (data?.total_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}
          >
            {(data?.total_pnl ?? 0) >= 0 ? "+" : ""}${Math.abs(data?.total_pnl ?? 0).toFixed(2)} P&L
          </span>
          <span>Win {data?.win_rate ?? 0}%</span>
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="py-10 text-center text-sm" style={{ color: "var(--ink-muted)" }}>
              Loading…
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Ticker</th>
                  <th>Dir</th>
                  <th>Type</th>
                  <th>Strategy</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Qty</th>
                  <th>P&L</th>
                  <th>Status</th>
                  <th>Exit Reason</th>
                  <th>Entry Time</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr>
                    <td colSpan={13} className="text-center py-10"
                        style={{ color: "var(--ink-muted)" }}>
                      No trades found
                    </td>
                  </tr>
                ) : (
                  trades.map((t) => (
                    <tr key={t.id}>
                      <td className="num text-xs" style={{ color: "var(--ink-muted)" }}>{t.id}</td>
                      <td className="font-semibold">{t.ticker}</td>
                      <td>
                        <span className={`badge ${t.direction === "long" ? "badge-green" : "badge-red"}`}>
                          {t.direction?.toUpperCase()}
                        </span>
                      </td>
                      <td className="text-xs">{t.option_type ?? "—"}</td>
                      <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                        {t.strategy_id ?? "—"}
                      </td>
                      <td className="num">${t.entry_price.toFixed(2)}</td>
                      <td className="num">
                        {t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}
                      </td>
                      <td className="num">{t.contracts}</td>
                      <td className="num font-medium"
                          style={{ color: (t.pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}>
                        {t.pnl != null
                          ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(2)}`
                          : "—"}
                      </td>
                      <td><StatusBadge status={t.status} /></td>
                      <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                        {t.exit_reason ?? "—"}
                      </td>
                      <td className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                        {t.entry_time
                          ? new Date(t.entry_time).toLocaleString("en-US", {
                              month: "2-digit", day: "2-digit",
                              hour: "2-digit", minute: "2-digit",
                            })
                          : "—"}
                      </td>
                      <td>
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
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
