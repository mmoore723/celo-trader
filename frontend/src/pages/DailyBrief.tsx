/**
 * DailyBrief.tsx — Daily session summary: today's trades, P&L, scanner picks, key events.
 */
import { useQuery } from "@tanstack/react-query";
import { api, type Trade } from "../lib/api";
import { useBotStore } from "../store/bot";

function fmt(n: number, prefix = "$") {
  return `${n >= 0 ? "+" : ""}${prefix}${Math.abs(n).toFixed(2)}`;
}

function today() {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}

export function DailyBrief() {
  const { status, logs } = useBotStore();

  const { data: tradesResp } = useQuery({
    queryKey: ["trades-today"],
    queryFn: () => api.trades.list("paper", "all"),
    refetchInterval: 30_000,
  });

  const { data: scanner = [] } = useQuery({
    queryKey: ["scanner"],
    queryFn: api.market.scanner,
    refetchInterval: 60_000,
  });

  // Filter to today's trades (by entry_time date)
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayTrades: Trade[] = (tradesResp?.trades ?? []).filter(
    (t) => t.entry_time && t.entry_time.startsWith(todayStr)
  );

  const wins  = todayTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const losses = todayTrades.filter((t) => (t.pnl ?? 0) < 0).length;
  const totalPnl = todayTrades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate = todayTrades.length ? Math.round((wins / todayTrades.length) * 100) : 0;

  // Key events from WS log stream (errors + signals)
  const keyEvents = logs
    .filter((l) =>
      l.event === "Trade_Signal" ||
      l.event === "entry_filled" ||
      l.event === "stop_hit" ||
      l.event === "stage1_exit" ||
      l.event === "stage2_exit" ||
      l.event === "time_box_exit" ||
      (l.level ?? "").toUpperCase() === "ERROR"
    )
    .slice(0, 20);

  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";

  return (
    <div className="p-4 flex flex-col gap-4 max-w-4xl">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Daily Brief</h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{today()}</p>
      </div>

      {/* Summary stat cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Session P&L",    value: fmt(status?.session_pnl ?? 0), color: (status?.session_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Today's Trades", value: todayTrades.length,           color: "var(--ink)" },
          { label: "Win Rate",       value: `${winRate}%`,                color: winRate >= 50 ? "var(--positive)" : "var(--negative)" },
          { label: "Account Balance",value: `$${(status?.account_balance ?? 0).toFixed(2)}`, color: "var(--ink)" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-3 flex flex-col gap-0.5">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num text-xl font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Two-column layout */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 1fr" }}>

        {/* Today's trades */}
        <div className="card flex flex-col">
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Today's Trades ({todayTrades.length})
            {todayTrades.length > 0 && (
              <span className="ml-2" style={{ color: pnlColor }}>
                {fmt(totalPnl)} total
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            {todayTrades.length === 0 ? (
              <p className="p-4 text-sm" style={{ color: "var(--ink-muted)" }}>
                No trades recorded today yet.
              </p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Ticker</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {todayTrades.map((t) => {
                    const pnl = t.pnl ?? 0;
                    return (
                      <tr key={t.id}>
                        <td className="font-semibold">{t.ticker}</td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>{t.strategy_id ?? "—"}</td>
                        <td className="num">${t.entry_price.toFixed(2)}</td>
                        <td className="num">{t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}</td>
                        <td className="num" style={{ color: pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                        </td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {t.exit_reason ?? (t.status === "open" ? <span className="badge badge-green">OPEN</span> : "—")}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Scanner picks + key events stacked */}
        <div className="flex flex-col gap-4">
          {/* Premarket scanner */}
          <div className="card flex flex-col">
            <div
              className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
              style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
            >
              Premarket Scanner Picks
            </div>
            {scanner.length === 0 ? (
              <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                No scan results — bot scans 9:00–9:25 ET
              </p>
            ) : (
              <div>
                {scanner.map((s, i) => (
                  <div
                    key={s.ticker}
                    className="px-3 py-2 flex items-center justify-between text-sm border-b last:border-0"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="text-xs num font-semibold w-5 text-center"
                        style={{ color: "var(--ink-faint)" }}
                      >
                        {i + 1}
                      </span>
                      <span className="font-semibold" style={{ color: "var(--ink)" }}>{s.ticker}</span>
                      <span className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                        {s.rvol.toFixed(1)}x RVOL
                      </span>
                    </div>
                    <span
                      className="text-xs num font-medium"
                      style={{ color: s.change_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
                    >
                      {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Key events */}
          <div className="card flex flex-col" style={{ minHeight: 120 }}>
            <div
              className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
              style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
            >
              Key Events
            </div>
            <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1 font-mono text-xs" style={{ maxHeight: 200 }}>
              {keyEvents.length === 0 ? (
                <p style={{ color: "var(--ink-muted)" }}>No key events yet — waiting for bot…</p>
              ) : (
                keyEvents.map((e, i) => {
                  const isError   = (e.level ?? "").toUpperCase() === "ERROR";
                  const isSignal  = e.event === "Trade_Signal" || e.event === "entry_filled";
                  const isExit    = ["stop_hit","stage1_exit","stage2_exit","time_box_exit"].includes(e.event ?? "");
                  const color = isError ? "var(--negative)" : isSignal ? "var(--positive)" : isExit ? "var(--warning)" : "var(--ink-muted)";
                  return (
                    <div key={i} style={{ color }}>
                      <span className="opacity-60">{e.ts ?? ""}</span>{" "}
                      {e.event && <span className="badge badge-blue mr-1">{e.event}</span>}
                      {String(e.message ?? "")}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Win/Loss breakdown */}
      {todayTrades.length > 0 && (
        <div className="card p-4 flex gap-6 text-sm">
          <div>
            <span style={{ color: "var(--ink-muted)" }}>Wins</span>
            <span className="ml-2 num font-semibold" style={{ color: "var(--positive)" }}>{wins}</span>
          </div>
          <div>
            <span style={{ color: "var(--ink-muted)" }}>Losses</span>
            <span className="ml-2 num font-semibold" style={{ color: "var(--negative)" }}>{losses}</span>
          </div>
          <div>
            <span style={{ color: "var(--ink-muted)" }}>Net P&L</span>
            <span className="ml-2 num font-semibold" style={{ color: pnlColor }}>{fmt(totalPnl)}</span>
          </div>
          {scanner.length > 0 && (
            <div>
              <span style={{ color: "var(--ink-muted)" }}>Top Pick</span>
              <span className="ml-2 font-semibold" style={{ color: "var(--ink)" }}>
                {scanner[0].ticker} ({scanner[0].rvol.toFixed(1)}× RVOL)
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
