/**
 * DailyBrief.tsx — Daily session summary with premarket scout report.
 * Notebook layout: ticker list on the left, full detail on the right.
 */
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Trade, type ScannerResult } from "../lib/api";
import { useBotStore } from "../store/bot";

function fmt(n: number) {
  return `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
}

function today() {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}

/** Plain-English scout summary for a scanner result. */
function scoutDetail(s: ScannerResult): string {
  const chg  = s.change_pct;
  const rvol = s.rvol;
  const dirWord =
    chg > 3   ? "sprinting upfield"   :
    chg > 1   ? "running hard up"     :
    chg > 0   ? "moving up slowly"    :
    chg < -3  ? "falling off a cliff" :
    chg < -1  ? "dropping fast"       :
                "treading water";
  const volWord =
    rvol >= 3   ? "the whole crowd is watching — insane volume" :
    rvol >= 2   ? "big crowd, way more activity than usual"      :
    rvol >= 1.5 ? "above-average buzz, good energy"              :
                  "lighter volume, proceed with caution";
  const edge = rvol >= 1.5 && Math.abs(chg) >= 1
    ? "High relative volume + a clear gap = the conditions where ORB setups work best."
    : "Needs stronger volume or a clearer move before it becomes a prime candidate.";
  return `This ticker is ${dirWord} premarket (${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%). ${volWord} (${rvol.toFixed(1)}× normal). ${edge}`;
}

function rankEmoji(rank: number, chg: number) {
  if (rank === 1) return "🥇";
  if (rank === 2) return "🥈";
  if (rank === 3) return "🥉";
  if (chg > 2)   return "🔥";
  if (chg < -2)  return "📉";
  return "👀";
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

  // Fetch user's settings watchlist so pinned tickers (e.g. XLE) always appear
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });
  const pinnedTickers: string[] = settings?.watchlist ?? [];

  // Merge scanner results + settings pins into one ordered list.
  // Scanner results come first (ranked), then any pins not already present.
  const scannerTickers = scanner.map((s) => s.ticker);
  const extraPins = pinnedTickers.filter((t) => !scannerTickers.includes(t));
  const allTickers = [...scannerTickers, ...extraPins];

  const [selected, setSelected] = useState<string>("");

  // Auto-select first ticker when data arrives
  useEffect(() => {
    if (!selected && allTickers.length > 0) setSelected(allTickers[0]);
  }, [allTickers.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Today's trades
  const _now = new Date();
  const todayTrades: Trade[] = (tradesResp?.trades ?? []).filter(
    (t) => t.entry_time && new Date(t.entry_time).toDateString() === _now.toDateString()
  );
  const wins     = todayTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const losses   = todayTrades.filter((t) => (t.pnl ?? 0) < 0).length;
  const totalPnl = todayTrades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = todayTrades.length ? Math.round((wins / todayTrades.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";

  // Signal events only (no heartbeat noise)
  const signalEvents = logs.filter((l) =>
    l.event === "Trade_Signal"  ||
    l.event === "entry_filled"  ||
    l.event === "stop_hit"      ||
    l.event === "stage1_exit"   ||
    l.event === "stage2_exit"   ||
    l.event === "time_box_exit" ||
    l.event === "kill_lock_active"
  ).slice(0, 15);

  // Detail pane — find scanner data for selected ticker (may be null for pin-only)
  const selectedScan = scanner.find((s) => s.ticker === selected) ?? null;
  const isPinOnly    = selected && !selectedScan;

  return (
    <div className="p-4 flex flex-col gap-4 max-w-4xl">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Daily Brief</h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{today()}</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Session P&L",     value: fmt(status?.session_pnl ?? 0),              color: (status?.session_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Today's Trades",  value: String(todayTrades.length),                  color: "var(--ink)" },
          { label: "Win Rate",        value: `${winRate}%`,                               color: winRate >= 50 ? "var(--positive)" : winRate > 0 ? "var(--negative)" : "var(--ink-muted)" },
          { label: "Account Balance", value: `$${(status?.account_balance ?? 0).toFixed(2)}`, color: "var(--ink)" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-3 flex flex-col gap-0.5">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num text-xl font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* ── Premarket Scout Report — notebook layout ── */}
      <div className="card overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 border-b" style={{ borderColor: "var(--border)" }}>
          <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>🏟️ Premarket Scout Report</h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
            Bot ranks tickers by RVOL + gap size. Pinned tickers from Settings always appear.
          </p>
        </div>

        {allTickers.length === 0 ? (
          <div className="px-4 py-8 text-sm text-center" style={{ color: "var(--ink-muted)" }}>
            No scan results yet — bot scans at <strong>9:00–9:25 ET</strong>.
            Add tickers to your watchlist in Settings to always see them here.
          </div>
        ) : (
          <div className="flex" style={{ minHeight: 260 }}>
            {/* Left: ticker list */}
            <div
              className="flex flex-col shrink-0 overflow-y-auto"
              style={{
                width: 140,
                borderRight: "1px solid var(--border)",
                background: "var(--muted)",
              }}
            >
              {allTickers.map((ticker) => {
                const s    = scanner.find((r) => r.ticker === ticker);
                const isActive = ticker === selected;
                const chg  = s?.change_pct ?? 0;
                const rank = s?.rank ?? 99;
                const emoji = s ? rankEmoji(rank, chg) : "📌";
                const chgColor = chg >= 0 ? "var(--positive)" : "var(--negative)";
                return (
                  <button
                    key={ticker}
                    onClick={() => setSelected(ticker)}
                    className="flex items-center gap-2 px-3 py-2.5 text-left transition-colors"
                    style={{
                      background: isActive ? "var(--card)" : "transparent",
                      borderLeft: isActive ? "3px solid var(--accent)" : "3px solid transparent",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span className="text-sm shrink-0">{emoji}</span>
                    <div className="min-w-0">
                      <div className="text-xs font-bold truncate" style={{ color: "var(--ink)" }}>
                        {ticker}
                      </div>
                      {s ? (
                        <div className="text-[10px] num font-semibold" style={{ color: chgColor }}>
                          {chg >= 0 ? "+" : ""}{chg.toFixed(1)}%
                        </div>
                      ) : (
                        <div className="text-[10px]" style={{ color: "var(--ink-faint)" }}>pinned</div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Right: detail pane */}
            <div className="flex-1 p-4 overflow-y-auto">
              {!selected ? (
                <p className="text-sm" style={{ color: "var(--ink-muted)" }}>Select a ticker to see details.</p>
              ) : isPinOnly ? (
                /* Settings-pinned ticker with no scanner data yet */
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl">📌</span>
                    <div>
                      <span className="text-xl font-bold" style={{ color: "var(--ink)" }}>{selected}</span>
                      <span className="ml-2 text-xs" style={{ color: "var(--ink-muted)" }}>Pinned from Settings</span>
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                    This ticker is in your watchlist but hasn't been ranked by the scanner yet.
                    Scanner runs at <strong>9:00–9:25 ET</strong> — check back after market open for RVOL and gap data.
                  </p>
                </div>
              ) : selectedScan ? (
                /* Full scanner detail */
                <div className="flex flex-col gap-4">
                  {/* Title row */}
                  <div className="flex items-start gap-3">
                    <span className="text-3xl shrink-0">{rankEmoji(selectedScan.rank, selectedScan.change_pct)}</span>
                    <div>
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <span className="text-xl font-bold" style={{ color: "var(--ink)" }}>{selectedScan.ticker}</span>
                        <span
                          className="text-sm num font-semibold"
                          style={{ color: selectedScan.change_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
                        >
                          {selectedScan.rank <= 3 ? `Draft Pick #${selectedScan.rank}` : "On the bench"}
                          {" · "}{selectedScan.change_pct >= 0 ? "+" : ""}{selectedScan.change_pct.toFixed(1)}%
                          {" · "}{selectedScan.rvol.toFixed(1)}× vol
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { label: "Price",  value: `$${selectedScan.price.toFixed(2)}`,                                    color: "var(--ink)" },
                      { label: "RVOL",   value: `${selectedScan.rvol.toFixed(2)}×`,                                     color: selectedScan.rvol >= 2 ? "var(--positive)" : "var(--ink)" },
                      { label: "ATR",    value: `$${selectedScan.atr.toFixed(2)}`,                                      color: "var(--ink)" },
                      { label: "Change", value: `${selectedScan.change_pct >= 0 ? "+" : ""}${selectedScan.change_pct.toFixed(2)}%`, color: selectedScan.change_pct >= 0 ? "var(--positive)" : "var(--negative)" },
                    ].map((stat) => (
                      <div
                        key={stat.label}
                        className="rounded-lg px-3 py-2 flex flex-col gap-0.5"
                        style={{ background: "var(--muted)" }}
                      >
                        <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>
                          {stat.label}
                        </span>
                        <span className="text-sm num font-semibold" style={{ color: stat.color }}>
                          {stat.value}
                        </span>
                      </div>
                    ))}
                  </div>

                  {/* Scout narrative */}
                  <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                    {scoutDetail(selectedScan)}
                  </p>

                  {/* Footer hint */}
                  <p className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                    💡 Bot filters 150+ stocks by RVOL + gap. No gap + no crowd = no edge.
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>

      {/* Today's trades */}
      <div className="card flex flex-col">
        <div
          className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider flex items-center gap-2"
          style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
        >
          Today's Trades ({todayTrades.length})
          {todayTrades.length > 0 && (
            <span style={{ color: pnlColor }}>{fmt(totalPnl)} total</span>
          )}
        </div>
        {todayTrades.length === 0 ? (
          <p className="p-4 text-sm" style={{ color: "var(--ink-muted)" }}>No trades recorded today yet.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr><th>Ticker</th><th>Strategy</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {todayTrades.map((t) => {
                    const pnl = t.pnl ?? 0;
                    const qty = t.contracts ?? 1;
                    return (
                      <tr key={t.id}>
                        <td className="font-semibold">{t.ticker}</td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>{t.strategy_id ?? "—"}</td>
                        <td className="num text-center"><span className="badge badge-blue">{qty}c</span></td>
                        <td className="num">${t.entry_price.toFixed(2)}</td>
                        <td className="num">{t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : "—"}</td>
                        <td className="num" style={{ color: pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                        </td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {t.exit_reason ?? (t.status === "open" ? "OPEN" : "—")}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-4 py-2 flex gap-6 text-sm border-t" style={{ borderColor: "var(--border)" }}>
              <span style={{ color: "var(--ink-muted)" }}>Wins <strong style={{ color: "var(--positive)" }}>{wins}</strong></span>
              <span style={{ color: "var(--ink-muted)" }}>Losses <strong style={{ color: "var(--negative)" }}>{losses}</strong></span>
              <span style={{ color: "var(--ink-muted)" }}>Net <strong style={{ color: pnlColor }}>{fmt(totalPnl)}</strong></span>
              <span style={{ color: "var(--ink-muted)" }}>Win Rate <strong>{winRate}%</strong></span>
            </div>
          </>
        )}
      </div>

      {/* Signal events */}
      {signalEvents.length > 0 && (
        <div className="card flex flex-col">
          <div
            className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
          >
            Trade Signals Today
          </div>
          <div className="p-2 flex flex-col gap-1 font-mono text-xs" style={{ maxHeight: 200, overflowY: "auto" }}>
            {signalEvents.map((e, i) => {
              const isSignal = e.event === "Trade_Signal" || e.event === "entry_filled";
              const isExit   = ["stop_hit","stage1_exit","stage2_exit","time_box_exit"].includes(e.event ?? "");
              const isRisk   = e.event === "kill_lock_active";
              const color    = isSignal ? "var(--positive)" : isExit ? "var(--warning)" : isRisk ? "var(--negative)" : "var(--ink-muted)";
              return (
                <div key={i} style={{ color }}>
                  <span className="opacity-60">{e.ts ?? ""}</span>{" "}
                  {e.event && <span className="badge badge-blue mr-1">{e.event}</span>}
                  {String(e.message ?? "")}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
