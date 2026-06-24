/**
 * DailyBrief.tsx — Daily session summary with premarket scout report.
 */
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

/** Generate a plain-English "scout report" for each scanned ticker. */
function scoutReport(s: ScannerResult, rank: number): { emoji: string; headline: string; detail: string } {
  const rvol = s.rvol;
  const chg  = s.change_pct;

  // Direction read
  const dirWord =
    chg > 3   ? "sprinting upfield"  :
    chg > 1   ? "running hard up"    :
    chg > 0   ? "moving up slowly"   :
    chg < -3  ? "falling off a cliff":
    chg < -1  ? "dropping fast"      :
                "treading water";

  // Volume read
  const volWord =
    rvol >= 3  ? "the whole crowd is watching — insane volume" :
    rvol >= 2  ? "big crowd, way more activity than usual"      :
    rvol >= 1.5? "above-average buzz, good energy"              :
                 "lighter volume, proceed with caution";

  // Emoji
  const emoji =
    rank === 1 ? "🥇" :
    rank === 2 ? "🥈" :
    rank === 3 ? "🥉" :
    chg > 2    ? "🔥" :
    chg < -2   ? "📉" : "👀";

  // Headline
  const headline =
    rank <= 3
      ? `Draft Pick #${rank} — ${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%, ${rvol.toFixed(1)}× volume`
      : `On the bench — ${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%, ${rvol.toFixed(1)}× volume`;

  const detail = `This ticker is ${dirWord} premarket (${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%). ${volWord} (${rvol.toFixed(1)}× normal). ${
    rvol >= 1.5 && Math.abs(chg) >= 1
      ? "The bot flagged it because high relative volume + a clear gap = the conditions where ORB setups work best."
      : "The bot is keeping an eye on it but needs stronger volume or a clearer move before treating it as a prime candidate."
  }`;

  return { emoji, headline, detail };
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

  // Today's trades
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayTrades: Trade[] = (tradesResp?.trades ?? []).filter(
    (t) => t.entry_time && t.entry_time.startsWith(todayStr)
  );
  const wins     = todayTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const losses   = todayTrades.filter((t) => (t.pnl ?? 0) < 0).length;
  const totalPnl = todayTrades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = todayTrades.length ? Math.round((wins / todayTrades.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";

  // Signal events only (no heartbeat noise)
  const signalEvents = logs.filter((l) =>
    l.event === "Trade_Signal"   ||
    l.event === "entry_filled"   ||
    l.event === "stop_hit"       ||
    l.event === "stage1_exit"    ||
    l.event === "stage2_exit"    ||
    l.event === "time_box_exit"  ||
    l.event === "kill_lock_active"
  ).slice(0, 15);

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
          { label: "Session P&L",     value: fmt(status?.session_pnl ?? 0),                     color: (status?.session_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Today's Trades",  value: String(todayTrades.length),                          color: "var(--ink)" },
          { label: "Win Rate",        value: `${winRate}%`,                                       color: winRate >= 50 ? "var(--positive)" : winRate > 0 ? "var(--negative)" : "var(--ink-muted)" },
          { label: "Account Balance", value: `$${(status?.account_balance ?? 0).toFixed(2)}`,     color: "var(--ink)" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-3 flex flex-col gap-0.5">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num text-xl font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Premarket Scout Report — the main event */}
      <div className="card p-4 flex flex-col gap-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            🏟️ Premarket Scout Report
          </h3>
          <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
            Think of this as a sports draft. The bot scans the market every morning at 9:00–9:25 ET
            and picks the loudest, fastest stocks on the playground — high relative volume and a clear
            direction before the bell. Low-volume stocks sitting on the bench get skipped. Here's today's draft board:
          </p>
        </div>

        {scanner.length === 0 ? (
          <div
            className="rounded-lg px-4 py-5 text-sm text-center"
            style={{ background: "var(--muted)", color: "var(--ink-muted)" }}
          >
            No scan results yet. The bot runs its draft pick at <strong>9:00–9:25 ET</strong> each morning.
            Start the bot before market open to populate this section.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {scanner.map((s) => {
              const { emoji, headline, detail } = scoutReport(s, s.rank);
              const chgColor = s.change_pct >= 0 ? "var(--positive)" : "var(--negative)";
              return (
                <div
                  key={s.ticker}
                  className="flex gap-4 p-3 rounded-lg"
                  style={{ background: "var(--muted)" }}
                >
                  <div className="text-2xl shrink-0 mt-0.5">{emoji}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="font-bold text-base" style={{ color: "var(--ink)" }}>
                        {s.ticker}
                      </span>
                      <span className="text-xs num font-semibold" style={{ color: chgColor }}>
                        {headline}
                      </span>
                    </div>
                    <p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                      {detail}
                    </p>
                    {/* Mini stats row */}
                    <div className="flex gap-4 mt-2">
                      {[
                        { label: "Price",  value: `$${s.price.toFixed(2)}` },
                        { label: "RVOL",   value: `${s.rvol.toFixed(2)}×`, color: s.rvol >= 2 ? "var(--positive)" : "var(--ink)" },
                        { label: "ATR",    value: `$${s.atr.toFixed(2)}` },
                        { label: "Change", value: `${s.change_pct >= 0 ? "+" : ""}${s.change_pct.toFixed(2)}%`, color: chgColor },
                      ].map((stat) => (
                        <div key={stat.label} className="flex flex-col">
                          <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>
                            {stat.label}
                          </span>
                          <span className="text-xs num font-semibold" style={{ color: stat.color ?? "var(--ink)" }}>
                            {stat.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
            <p className="text-xs px-1" style={{ color: "var(--ink-faint)" }}>
              💡 Why these? The bot filters 150+ liquid stocks down to the ones with the highest relative volume
              AND a meaningful pre-market gap. No gap + no crowd = no edge. The bot only plays when the odds are in its favor.
            </p>
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
          <p className="p-4 text-sm" style={{ color: "var(--ink-muted)" }}>
            No trades recorded today yet.
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
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

      {/* Signal events — only meaningful trades, no system noise */}
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
