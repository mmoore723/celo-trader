/**
 * DailyBrief.tsx — Daily session hub with Pre-Market scout and Post-Market recap.
 * Pre-Market tab : scanner results ranked by RVOL + gap — who to watch today.
 * Post-Market tab: plain-language trade recap anyone can understand.
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

/** Translate a raw exit_reason into a simple sentence anyone can understand. */
function simpleExit(reason?: string, pnl?: number): string {
  if (!reason) return (pnl ?? 0) > 0 ? "hit the profit goal" : "cut the losses";
  if (reason.includes("stage1"))                               return "hit the profit target 🎯";
  if (reason.includes("atr_trail") || reason.includes("stage2")) return "price started pulling back — locked in the gains";
  if (reason.includes("hard_stop") || reason.includes("stop")) return "price dropped too much — the safety net kicked in ⛔";
  if (reason.includes("vwap"))                                 return "momentum died — got out early";
  if (reason.includes("time_cap"))                             return "hit the time limit ⏱";
  if (reason.includes("peak_giveback"))                        return "gave back too much of the gain — took what was left";
  if (reason.includes("momentum_dead"))                        return "trade went nowhere — cut it loose";
  return "exit signal triggered";
}

/** Day grade based on net P&L. */
function dayGrade(pnl: number) {
  if (pnl > 200)  return { letter: "A+", emoji: "🏆", msg: "Incredible day. The bot was locked in." };
  if (pnl > 100)  return { letter: "A",  emoji: "🔥", msg: "Great day! Strong profits across the board." };
  if (pnl > 0)    return { letter: "B",  emoji: "✅", msg: "Good day. Finished in the green — that's what matters." };
  if (pnl > -50)  return { letter: "C",  emoji: "😐", msg: "Roughly break-even. Market was tough today." };
  if (pnl > -150) return { letter: "D",  emoji: "📉", msg: "Tough day. Small loss — review the exits and move on." };
  return             { letter: "F",  emoji: "🔴", msg: "Hard day. Big loss. One rough session is part of the game — review it and keep going." };
}

// ── Post-Market Report ──────────────────────────────────────────────────────────
function PostMarketReport({ trades }: { trades: Trade[] }) {
  const closed   = trades.filter(t => t.status === "closed");
  const wins     = closed.filter(t => (t.pnl ?? 0) > 0);
  const losses   = closed.filter(t => (t.pnl ?? 0) <= 0);
  const totalPnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = closed.length ? Math.round((wins.length / closed.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";
  const grade    = dayGrade(totalPnl);
  const avgWin   = wins.length   ? wins.reduce((s,   t) => s + (t.pnl ?? 0), 0) / wins.length   : 0;
  const avgLoss  = losses.length ? losses.reduce((s, t) => s + (t.pnl ?? 0), 0) / losses.length : 0;

  if (closed.length === 0) {
    return (
      <div className="card p-8 text-center flex flex-col items-center gap-2">
        <p className="text-3xl">📋</p>
        <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>No completed trades yet today.</p>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          This report will fill in once the bot closes its first position.
        </p>
      </div>
    );
  }

  // Build the summary paragraph in plain language
  const dirWord  = totalPnl >= 0 ? "made" : "lost";
  const absAmt   = Math.abs(totalPnl).toFixed(2);
  const perfDesc = winRate >= 60 ? "winning more than losing" : winRate >= 40 ? "splitting about 50/50" : "losing more than winning";
  const avgNote  =
    wins.length > 0 && losses.length > 0
      ? ` Average winning trade: ${fmt(avgWin)}. Average losing trade: ${fmt(avgLoss)}.${
          Math.abs(avgWin) > Math.abs(avgLoss)
            ? " Wins are bigger than losses — that's the right direction. ✅"
            : " Losses are costing more than wins are paying. Worth watching."
        }`
      : "";
  const outcomeNote = totalPnl >= 0
    ? "Finishing green means the bot did its job today. Keep it running."
    : "Finishing red is part of trading — even the best bots have down days. The important thing is the bot stayed disciplined and didn't blow up the account.";

  return (
    <div className="flex flex-col gap-4">

      {/* Grade banner */}
      <div className="card p-4 flex items-center gap-4">
        <div
          className="rounded-2xl shrink-0 flex items-center justify-center font-black text-2xl"
          style={{ width: 68, height: 68, background: "var(--muted)", color: pnlColor }}
        >
          {grade.letter}
        </div>
        <div className="flex-1">
          <p className="text-base font-bold" style={{ color: "var(--ink)" }}>
            {grade.emoji} Today's Grade: <span style={{ color: pnlColor }}>{grade.letter}</span>
          </p>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{grade.msg}</p>
          <p className="text-xs mt-1" style={{ color: "var(--ink-faint)" }}>
            {closed.length} trade{closed.length !== 1 ? "s" : ""} · {wins.length}W / {losses.length}L · {winRate}% win rate · Net{" "}
            <strong style={{ color: pnlColor }}>{fmt(totalPnl)}</strong>
          </p>
        </div>
      </div>

      {/* Plain-English summary */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--ink)" }}>📖 What Happened Today — In Plain English</h3>
        <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          Today the bot took <strong>{closed.length} trade{closed.length !== 1 ? "s" : ""}</strong>, {perfDesc}.
          The account {dirWord} <strong style={{ color: pnlColor }}>${absAmt}</strong>.{avgNote} {outcomeNote}
        </p>
      </div>

      {/* Trade-by-trade */}
      <div className="card">
        <div
          className="px-4 py-2 border-b text-xs font-semibold uppercase tracking-wide"
          style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
        >
          Trade-by-Trade Recap
        </div>
        <div className="flex flex-col">
          {closed.map((t, i) => {
            const pnl   = t.pnl ?? 0;
            const isWin = pnl > 0;
            const ep    = t.entry_price ?? 0;
            const xp    = t.exit_price ?? ep;
            const qty   = t.contracts ?? 1;
            const dir   = (t.option_type ?? "call").toUpperCase();
            const exitTxt = simpleExit(t.exit_reason, pnl);
            return (
              <div
                key={t.id}
                className="px-4 py-3 flex gap-3 items-start"
                style={{ borderBottom: i < closed.length - 1 ? "1px solid var(--border)" : undefined }}
              >
                {/* W / L badge */}
                <div
                  className="shrink-0 rounded-full w-7 h-7 flex items-center justify-center text-xs font-bold mt-0.5"
                  style={{ background: isWin ? "var(--positive)" : "var(--negative)", color: "#fff" }}
                >
                  {isWin ? "W" : "L"}
                </div>

                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                    Trade #{i + 1} — {t.ticker} {dir}
                    <span className="ml-1 text-xs font-normal" style={{ color: "var(--ink-muted)" }}>
                      · {qty} contract{qty !== 1 ? "s" : ""}{t.strategy_id ? ` · ${t.strategy_id}` : ""}
                    </span>
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                    Bought the contract at <strong>${ep.toFixed(2)}</strong>, sold at <strong>${xp.toFixed(2)}</strong>.
                    {" "}Result:{" "}
                    <strong style={{ color: isWin ? "var(--positive)" : "var(--negative)" }}>
                      {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                    </strong>
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--ink-faint)" }}>
                    Why we got out: {exitTxt}
                  </p>
                </div>

                <div
                  className="shrink-0 num font-bold text-sm"
                  style={{ color: isWin ? "var(--positive)" : "var(--negative)" }}
                >
                  {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Key takeaway */}
      <div className="card p-4" style={{ borderLeft: "3px solid var(--accent)" }}>
        <h3 className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--ink-muted)" }}>
          💡 Key Takeaway
        </h3>
        <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          {wins.length > losses.length
            ? `Winning more than losing — that's the most important stat in trading. As long as the average win ($${Math.abs(avgWin).toFixed(2)}) stays bigger than the average loss ($${Math.abs(avgLoss).toFixed(2)}), keep running the bot consistently.`
            : losses.length > wins.length
            ? `More losses than wins today. That's normal — what matters is whether the average win ($${Math.abs(avgWin).toFixed(2)}) is bigger than the average loss ($${Math.abs(avgLoss).toFixed(2)}). If wins cost less and pay more, you're still on the right track. Check the Performance tab for the full picture.`
            : `Even split today. Small improvements to entry timing or stop placement could push this into consistent profitability. Check the Performance tab for patterns over time.`
          }
        </p>
      </div>

    </div>
  );
}

// ── Main DailyBrief ──────────────────────────────────────────────────────────────
export function DailyBrief() {
  const { status, logs } = useBotStore();

  const { data: tradesResp } = useQuery({
    queryKey: ["trades-today"],
    queryFn:  () => api.trades.list("paper", "all"),
    refetchInterval: 30_000,
  });

  const { data: scanner = [] } = useQuery({
    queryKey: ["scanner"],
    queryFn:  api.market.scanner,
    refetchInterval: 60_000,
  });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn:  api.settings.get,
    staleTime: 60_000,
  });
  const pinnedTickers: string[] = settings?.watchlist ?? [];

  const scannerTickers = scanner.map((s) => s.ticker);
  const extraPins      = pinnedTickers.filter((t) => !scannerTickers.includes(t));
  const allTickers     = [...scannerTickers, ...extraPins];

  const [selected, setSelected] = useState<string>("");

  // Auto-select first ticker when data arrives
  useEffect(() => {
    if (!selected && allTickers.length > 0) setSelected(allTickers[0]);
  }, [allTickers.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-default to Post-Market after 4 pm (approximate ET)
  const [briefTab, setBriefTab] = useState<"premarket" | "postmarket">(
    new Date().getHours() >= 16 ? "postmarket" : "premarket"
  );

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

  const signalEvents = logs.filter((l) =>
    l.event === "Trade_Signal"  ||
    l.event === "entry_filled"  ||
    l.event === "stop_hit"      ||
    l.event === "stage1_exit"   ||
    l.event === "stage2_exit"   ||
    l.event === "time_box_exit" ||
    l.event === "kill_lock_active"
  ).slice(0, 15);

  const selectedScan = scanner.find((s) => s.ticker === selected) ?? null;
  const isPinOnly    = selected && !selectedScan;

  return (
    <div className="p-4 flex flex-col gap-4 max-w-4xl">

      {/* Header */}
      <div>
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Daily Brief</h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{today()}</p>
      </div>

      {/* Stat cards — always visible */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Session P&L",     value: fmt(status?.session_pnl ?? 0),                   color: (status?.session_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Today's Trades",  value: String(todayTrades.length),                        color: "var(--ink)" },
          { label: "Win Rate",        value: `${winRate}%`,                                     color: winRate >= 50 ? "var(--positive)" : winRate > 0 ? "var(--negative)" : "var(--ink-muted)" },
          { label: "Account Balance", value: `$${(status?.account_balance ?? 0).toFixed(2)}`,  color: "var(--ink)" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-3 flex flex-col gap-0.5">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num text-xl font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Tab switcher */}
      <div className="flex gap-2">
        <button
          className={`btn btn-sm ${briefTab === "premarket" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setBriefTab("premarket")}
        >
          🏟️ Pre-Market
        </button>
        <button
          className={`btn btn-sm ${briefTab === "postmarket" ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setBriefTab("postmarket")}
        >
          📊 Post-Market
        </button>
      </div>

      {/* ── Pre-Market Tab ── */}
      {briefTab === "premarket" && (
        <>
          {/* Premarket Scout Report — notebook layout */}
          <div className="card overflow-hidden">
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
                  style={{ width: 140, borderRight: "1px solid var(--border)", background: "var(--muted)" }}
                >
                  {allTickers.map((ticker) => {
                    const s       = scanner.find((r) => r.ticker === ticker);
                    const isActive = ticker === selected;
                    const chg     = s?.change_pct ?? 0;
                    const rank    = s?.rank ?? 99;
                    const emoji   = s ? rankEmoji(rank, chg) : "📌";
                    const chgColor = chg >= 0 ? "var(--positive)" : "var(--negative)";
                    return (
                      <button
                        key={ticker}
                        onClick={() => setSelected(ticker)}
                        className="flex items-center gap-2 px-3 py-2.5 text-left transition-colors"
                        style={{
                          background:  isActive ? "var(--card)" : "transparent",
                          borderLeft:  isActive ? "3px solid var(--accent)" : "3px solid transparent",
                          borderBottom: "1px solid var(--border)",
                        }}
                      >
                        <span className="text-sm shrink-0">{emoji}</span>
                        <div className="min-w-0">
                          <div className="text-xs font-bold truncate" style={{ color: "var(--ink)" }}>{ticker}</div>
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
                        Scanner runs at <strong>9:00–9:25 ET</strong> — check back after market open.
                      </p>
                    </div>
                  ) : selectedScan ? (
                    <div className="flex flex-col gap-4">
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

                      <div className="grid grid-cols-4 gap-3">
                        {[
                          { label: "Price",  value: `$${selectedScan.price.toFixed(2)}`,                                                      color: "var(--ink)" },
                          { label: "RVOL",   value: `${selectedScan.rvol.toFixed(2)}×`,                                                       color: selectedScan.rvol >= 2 ? "var(--positive)" : "var(--ink)" },
                          { label: "ATR",    value: `$${selectedScan.atr.toFixed(2)}`,                                                         color: "var(--ink)" },
                          { label: "Change", value: `${selectedScan.change_pct >= 0 ? "+" : ""}${selectedScan.change_pct.toFixed(2)}%`,       color: selectedScan.change_pct >= 0 ? "var(--positive)" : "var(--negative)" },
                        ].map((stat) => (
                          <div key={stat.label} className="rounded-lg px-3 py-2 flex flex-col gap-0.5" style={{ background: "var(--muted)" }}>
                            <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{stat.label}</span>
                            <span className="text-sm num font-semibold" style={{ color: stat.color }}>{stat.value}</span>
                          </div>
                        ))}
                      </div>

                      <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                        {scoutDetail(selectedScan)}
                      </p>
                      <p className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                        💡 Bot filters 150+ stocks by RVOL + gap. No gap + no crowd = no edge.
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>
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
        </>
      )}

      {/* ── Post-Market Tab ── */}
      {briefTab === "postmarket" && (
        <>
          <PostMarketReport trades={todayTrades} />

          {/* Raw trade table for reference */}
          {todayTrades.length > 0 && (
            <div className="card flex flex-col">
              <div
                className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider flex items-center gap-2"
                style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}
              >
                Full Trade Log ({todayTrades.length})
                <span style={{ color: pnlColor }}>{fmt(totalPnl)} total</span>
              </div>
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
            </div>
          )}
        </>
      )}

    </div>
  );
}
