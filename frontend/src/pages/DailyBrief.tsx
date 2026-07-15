/**
 * DailyBrief.tsx — Daily session hub with Pre-Market scout and Post-Market recap.
 * Pre-Market tab : rich premarket report from /api/market/premarket — ALL watchlist tickers.
 * Post-Market tab: plain-language trade recap anyone can understand.
 */
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Trade, type ScannerResult, type PremarketTicker } from "../lib/api";
import { useBotStore } from "../store/bot";

function fmt(n: number) {
  return `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
}

function today() {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}

/** Rank emoji for scanner-only tickers (no premarket data). */
function rankEmoji(rank: number, chg: number) {
  if (rank === 1) return "🥇";
  if (rank === 2) return "🥈";
  if (rank === 3) return "🥉";
  if (chg > 2)   return "🔥";
  if (chg < -2)  return "📉";
  return "👀";
}

/** Text color for a setup grade. */
function gradeColor(g: string): string {
  if (g === "A+") return "#00e676";
  if (g === "A")  return "#00c853";
  if (g === "B")  return "#29b6f6";
  if (g === "C")  return "#ffd740";
  return "var(--ink-faint)";
}

/** Background for a setup grade badge. */
function gradeBg(g: string): string {
  if (g === "A+") return "rgba(0,230,118,0.15)";
  if (g === "A")  return "rgba(0,200,83,0.12)";
  if (g === "B")  return "rgba(41,182,246,0.12)";
  if (g === "C")  return "rgba(255,215,64,0.10)";
  return "rgba(255,255,255,0.05)";
}

/** Translate raw exit_reason to a plain sentence. */
function simpleExit(reason?: string, pnl?: number): string {
  if (!reason) return (pnl ?? 0) > 0 ? "hit the profit goal" : "cut the losses";
  if (reason.includes("stage1"))                                return "hit the profit target 🎯";
  if (reason.includes("atr_trail") || reason.includes("stage2")) return "price started pulling back — locked in the gains";
  if (reason.includes("hard_stop") || reason.includes("stop"))  return "price dropped too much — the safety net kicked in ⛔";
  if (reason.includes("vwap"))                                   return "momentum died — got out early";
  if (reason.includes("time_cap"))                               return "hit the time limit ⏱";
  if (reason.includes("peak_giveback"))                          return "gave back too much of the gain — took what was left";
  if (reason.includes("momentum_dead"))                          return "trade went nowhere — cut it loose";
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

// ── Post-Market Report ─────────────────────────────────────────────────────────
function PostMarketReport({ trades }: { trades: Trade[] }) {
  const closed   = trades.filter(t => t.status === "closed");
  const wins     = closed.filter(t => (t.pnl ?? 0) > 0);
  const losses   = closed.filter(t => (t.pnl ?? 0) <= 0);
  const totalPnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = closed.length ? Math.round((wins.length / closed.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";
  const grade    = dayGrade(totalPnl);
  const avgWin   = wins.length   ? wins.reduce((s, t) => s + (t.pnl ?? 0), 0) / wins.length   : 0;
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
            const pnl     = t.pnl ?? 0;
            const isWin   = pnl > 0;
            const ep      = t.entry_price ?? 0;
            const xp      = t.exit_price ?? ep;
            const qty     = t.contracts ?? 1;
            const dir     = (t.option_type ?? "call").toUpperCase();
            const exitTxt = simpleExit(t.exit_reason, pnl);
            return (
              <div
                key={t.id}
                className="px-4 py-3 flex gap-3 items-start"
                style={{ borderBottom: i < closed.length - 1 ? "1px solid var(--border)" : undefined }}
              >
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
                    Bought at <strong>${ep.toFixed(2)}</strong>, sold at <strong>${xp.toFixed(2)}</strong>.
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
            ? `More losses than wins today. What matters is whether wins ($${Math.abs(avgWin).toFixed(2)} avg) are bigger than losses ($${Math.abs(avgLoss).toFixed(2)} avg). Check the Performance tab for the full picture.`
            : `Even split today. Small improvements to entry timing or stop placement could push this into consistent profitability. Check Performance for patterns over time.`
          }
        </p>
      </div>
    </div>
  );
}

// ── Rich Premarket Detail Pane ─────────────────────────────────────────────────
function PremarketDetail({ pm }: { pm: PremarketTicker }) {
  const range    = pm.prev_high - pm.prev_low;
  const pricePos = range > 0 ? Math.max(0, Math.min(100, ((pm.price - pm.prev_low) / range) * 100)) : 50;
  const closePos = range > 0 ? Math.max(0, Math.min(100, ((pm.prev_close - pm.prev_low) / range) * 100)) : 50;
  const dirColor = pm.direction === "calls" ? "var(--positive)" : pm.direction === "puts" ? "var(--negative)" : "var(--ink-muted)";
  const dirLabel = pm.direction === "calls" ? "🟢 CALLS" : pm.direction === "puts" ? "🔴 PUTS" : "⚪ NEUTRAL";

  return (
    <div className="flex flex-col gap-3">
      {/* Header: grade + ticker + price + direction + gap */}
      <div className="flex items-center gap-2 flex-wrap">
        <div
          className="text-[10px] font-black px-2 py-0.5 rounded-full"
          style={{ background: gradeBg(pm.grade), color: gradeColor(pm.grade), border: `1px solid ${gradeColor(pm.grade)}50` }}
        >
          {pm.grade}
        </div>
        <span className="text-xl font-bold" style={{ color: "var(--ink)" }}>{pm.ticker}</span>
        <span className="num text-base font-semibold" style={{ color: "var(--ink-muted)" }}>${pm.price.toFixed(2)}</span>
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded-full"
          style={{ color: dirColor, background: "var(--muted)" }}
        >
          {dirLabel}
        </span>
        <span
          className="num text-sm font-semibold ml-auto"
          style={{ color: pm.gap_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
        >
          {pm.gap_pct >= 0 ? "+" : ""}{pm.gap_pct.toFixed(2)}% gap
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1.5">
        {([
          { label: "RVOL",       value: `${pm.rvol.toFixed(2)}×`,         color: pm.rvol >= 2 ? "var(--positive)" : pm.rvol >= 1.5 ? "#ffd740" : "var(--ink)" },
          { label: "ATR",        value: `$${pm.atr.toFixed(2)}`,           color: "var(--ink)" },
          { label: "ATR%",       value: `${pm.atr_pct.toFixed(2)}%`,       color: "var(--ink)" },
          { label: "Prev Close", value: `$${pm.prev_close.toFixed(2)}`,    color: "var(--ink-muted)" },
          { label: "Prev High",  value: `$${pm.prev_high.toFixed(2)}`,     color: "var(--positive)" },
          { label: "Prev Low",   value: `$${pm.prev_low.toFixed(2)}`,      color: "var(--negative)" },
        ] as {label:string;value:string;color:string}[]).map(s => (
          <div key={s.label} className="rounded-md px-2 py-1.5 flex flex-col" style={{ background: "var(--muted)" }}>
            <span className="text-[9px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{s.label}</span>
            <span className="text-xs num font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Price position bar: prev_low ←→ prev_high with close tick + current price dot */}
      <div className="rounded-md px-3 py-2.5" style={{ background: "var(--muted)" }}>
        <div className="flex justify-between text-[9px] mb-1.5" style={{ color: "var(--ink-faint)" }}>
          <span>▼ ${pm.prev_low.toFixed(2)}</span>
          <span>Yesterday's Range</span>
          <span>▲ ${pm.prev_high.toFixed(2)}</span>
        </div>
        <div className="relative rounded-full" style={{ height: 6, background: "rgba(255,255,255,0.07)" }}>
          {/* Prev close tick */}
          <div
            className="absolute top-0 bottom-0"
            style={{ left: `${closePos}%`, width: 2, background: "var(--ink-faint)", transform: "translateX(-50%)" }}
          />
          {/* Current price dot */}
          <div
            className="absolute rounded-full"
            style={{
              left: `${pricePos}%`, top: "50%",
              width: 10, height: 10,
              transform: "translate(-50%, -50%)",
              background: pm.gap_pct >= 0 ? "var(--positive)" : "var(--negative)",
              boxShadow: `0 0 6px ${pm.gap_pct >= 0 ? "#00c853" : "#ef5350"}`,
            }}
          />
        </div>
        <div className="text-[9px] mt-1 text-center" style={{ color: "var(--ink-faint)" }}>
          │ prev close · ● current price · {pm.gap_pct >= 0 ? "gapping up" : "gapping down"}
        </div>
      </div>

      {/* Trade plan */}
      <div
        className="rounded-md p-3 flex flex-col gap-1.5"
        style={{ background: "var(--muted)", borderLeft: `3px solid ${dirColor}` }}
      >
        <div className="text-[10px] font-bold uppercase tracking-wide mb-0.5" style={{ color: "var(--ink-muted)" }}>
          📋 Trade Plan
        </div>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>🎯 Entry:</span> {pm.entry_note}
        </p>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>🛑 Stop:</span> {pm.stop_note}
        </p>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>💰 Target:</span> {pm.target_note}
        </p>
      </div>

      {/* Key levels */}
      {pm.key_levels.length > 0 && (
        <div className="rounded-md overflow-hidden" style={{ background: "var(--muted)" }}>
          <div
            className="px-3 py-1.5 text-[9px] font-bold uppercase tracking-wide"
            style={{ color: "var(--ink-faint)", borderBottom: "1px solid var(--border)" }}
          >
            Key Levels
          </div>
          {pm.key_levels.map((lv, i) => {
            const lvColor =
              lv.type === "resistance" ? "var(--negative)" :
              lv.type === "support"    ? "var(--positive)" :
              "var(--ink-muted)";
            return (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-1.5"
                style={{ borderBottom: i < pm.key_levels.length - 1 ? "1px solid var(--border)" : undefined }}
              >
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{lv.label}</span>
                <span className="text-xs num font-semibold" style={{ color: lvColor }}>${lv.price.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Setup notes */}
      {pm.setup_notes && (
        <div className="rounded-md p-3" style={{ background: "var(--muted)" }}>
          <div className="text-[9px] font-bold uppercase tracking-wide mb-1" style={{ color: "var(--ink-faint)" }}>Analysis</div>
          <p className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>{pm.setup_notes}</p>
        </div>
      )}
    </div>
  );
}

// ── Main DailyBrief ────────────────────────────────────────────────────────────
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

  // Rich premarket endpoint — includes ALL watchlist tickers with live Alpaca + yfinance data
  const { data: premarket = [], isLoading: pmLoading } = useQuery<PremarketTicker[]>({
    queryKey: ["premarket"],
    queryFn:  () => api.market.premarket(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const pmMap = new Map<string, PremarketTicker>(premarket.map(p => [p.ticker, p]));

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn:  api.settings.get,
    staleTime: 60_000,
  });
  const pinnedTickers: string[] = settings?.watchlist ?? [];

  // Unified list: premarket (has rich data) first, then scanner-only, then any pinned extras
  const pmTickers      = premarket.map(p => p.ticker);
  const scannerTickers = scanner.map((s: ScannerResult) => s.ticker);
  const allTickers     = [...new Set([...pmTickers, ...scannerTickers, ...pinnedTickers])];

  const [selected, setSelected]   = useState<string>("");
  const [briefTab, setBriefTab]   = useState<"premarket" | "postmarket">(
    new Date().getHours() >= 16 ? "postmarket" : "premarket"
  );

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

  const signalEvents = logs.filter((l) =>
    l.event === "Trade_Signal"  ||
    l.event === "entry_filled"  ||
    l.event === "stop_hit"      ||
    l.event === "stage1_exit"   ||
    l.event === "stage2_exit"   ||
    l.event === "time_box_exit" ||
    l.event === "kill_lock_active"
  ).slice(0, 15);

  const selectedPm   = pmMap.get(selected) ?? null;
  const selectedScan = scanner.find((s: ScannerResult) => s.ticker === selected) ?? null;

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
          { label: "Session P&L",     value: fmt(status?.session_pnl ?? 0),                  color: (status?.session_pnl ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Today's Trades",  value: String(todayTrades.length),                       color: "var(--ink)" },
          { label: "Win Rate",        value: `${winRate}%`,                                    color: winRate >= 50 ? "var(--positive)" : winRate > 0 ? "var(--negative)" : "var(--ink-muted)" },
          { label: "Account Balance", value: `$${(status?.account_balance ?? 0).toFixed(2)}`, color: "var(--ink)" },
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
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "var(--border)" }}>
              <div>
                <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>🏟️ Premarket Report</h3>
                <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                  All watchlist tickers · grade, key levels, trade plan · auto-refreshes every 60s.
                </p>
              </div>
              {pmLoading && (
                <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "var(--muted)", color: "var(--ink-faint)" }}>
                  Loading…
                </span>
              )}
            </div>

            {allTickers.length === 0 ? (
              <div className="px-4 py-8 text-sm text-center" style={{ color: "var(--ink-muted)" }}>
                No scan results yet — scanner runs at <strong>9:00–9:25 ET</strong>.
                Add tickers to your watchlist in Settings to always see them here.
              </div>
            ) : (
              <div className="flex" style={{ minHeight: 340 }}>

                {/* Left: ticker list */}
                <div
                  className="flex flex-col shrink-0 overflow-y-auto"
                  style={{ width: 150, borderRight: "1px solid var(--border)", background: "var(--muted)" }}
                >
                  {allTickers.map((ticker) => {
                    const pm       = pmMap.get(ticker);
                    const s        = scanner.find((r: ScannerResult) => r.ticker === ticker);
                    const isActive = ticker === selected;
                    const grade    = pm?.grade ?? "—";
                    const chg      = pm?.gap_pct ?? s?.change_pct ?? 0;
                    const chgColor = chg >= 0 ? "var(--positive)" : "var(--negative)";
                    return (
                      <button
                        key={ticker}
                        onClick={() => setSelected(ticker)}
                        className="flex items-center gap-2 px-3 py-2.5 text-left transition-colors w-full"
                        style={{
                          background:   isActive ? "var(--card)" : "transparent",
                          borderLeft:   isActive ? "3px solid var(--accent)" : "3px solid transparent",
                          borderBottom: "1px solid var(--border)",
                        }}
                      >
                        {/* Grade badge (if premarket data) or rank emoji */}
                        {pm ? (
                          <div
                            className="text-[9px] font-black rounded px-1 py-0.5 shrink-0"
                            style={{ background: gradeBg(grade), color: gradeColor(grade), minWidth: 24, textAlign: "center" }}
                          >
                            {grade}
                          </div>
                        ) : (
                          <span className="text-sm shrink-0">
                            {s ? rankEmoji(s.rank, s.change_pct) : "📌"}
                          </span>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-bold truncate" style={{ color: "var(--ink)" }}>{ticker}</div>
                          <div
                            className="text-[10px] num font-semibold"
                            style={{ color: (pm || s) ? chgColor : "var(--ink-faint)" }}
                          >
                            {(pm || s) ? `${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%` : "no data"}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {/* Right: detail pane */}
                <div className="flex-1 p-4 overflow-y-auto" style={{ minWidth: 0 }}>
                  {!selected ? (
                    <p className="text-sm" style={{ color: "var(--ink-muted)" }}>Select a ticker to see details.</p>
                  ) : selectedPm ? (
                    /* Rich premarket report */
                    <PremarketDetail pm={selectedPm} />
                  ) : selectedScan ? (
                    /* Fallback: scanner data only */
                    <div className="flex flex-col gap-4">
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <span className="text-xl font-bold" style={{ color: "var(--ink)" }}>{selectedScan.ticker}</span>
                        <span
                          className="text-sm num font-semibold"
                          style={{ color: selectedScan.change_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
                        >
                          {selectedScan.change_pct >= 0 ? "+" : ""}{selectedScan.change_pct.toFixed(2)}%
                        </span>
                        <span className="text-xs" style={{ color: "var(--ink-muted)" }}>· Rank #{selectedScan.rank}</span>
                      </div>
                      <div className="grid grid-cols-4 gap-2">
                        {[
                          { label: "Price",  value: `$${selectedScan.price.toFixed(2)}`,                                                       color: "var(--ink)" },
                          { label: "RVOL",   value: `${selectedScan.rvol.toFixed(2)}×`,                                                        color: selectedScan.rvol >= 2 ? "var(--positive)" : "var(--ink)" },
                          { label: "ATR",    value: `$${selectedScan.atr.toFixed(2)}`,                                                          color: "var(--ink)" },
                          { label: "Change", value: `${selectedScan.change_pct >= 0 ? "+" : ""}${selectedScan.change_pct.toFixed(2)}%`,        color: selectedScan.change_pct >= 0 ? "var(--positive)" : "var(--negative)" },
                        ].map(stat => (
                          <div key={stat.label} className="rounded-lg px-3 py-2 flex flex-col gap-0.5" style={{ background: "var(--muted)" }}>
                            <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{stat.label}</span>
                            <span className="text-sm num font-semibold" style={{ color: stat.color }}>{stat.value}</span>
                          </div>
                        ))}
                      </div>
                      <p className="text-xs" style={{ color: "var(--ink-faint)" }}>
                        Rich premarket data not yet available. Full report loads when the scanner runs (9:00–9:25 ET).
                      </p>
                    </div>
                  ) : (
                    /* Pinned but no data yet */
                    <div className="flex flex-col gap-2">
                      <span className="text-2xl">📌</span>
                      <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{selected}</p>
                      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
                        Pinned ticker — premarket data loads when the scanner runs at 9:00–9:25 ET.
                      </p>
                    </div>
                  )}
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
