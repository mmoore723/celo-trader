/**
 * DailyBrief.tsx — Daily session hub with Pre-Market scout and Post-Market recap.
 * Pre-Market tab : rich premarket report from /api/market/premarket — ALL watchlist tickers.
 * Post-Market tab: plain-language trade recap anyone can understand.
 */
import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Trade, type PremarketTicker } from "../lib/api";
import { useBotStore } from "../store/bot";
import { Tooltip } from "../components/Tooltip";
import { GLOSSARY } from "../lib/glossary";
import { preferredDailyBriefTicker } from "../lib/dailyBriefSelection.js";
import { premarketDayOutlook } from "../lib/premarketOutlook.js";
import { DailyEvidencePanel } from "../components/DailyEvidencePanel";
import type { DailyEvidenceScorecard } from "../lib/api";
import { isTradingDayFinal, newYorkDateKey } from "../lib/marketSession.js";

function fmt(n: number) {
  return `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}`;
}

function today() {
  return new Date().toLocaleDateString("en-US", {
    timeZone: "America/New_York",
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
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
  if (g === "A+") return "rgba(0,230,118,0.22)";
  if (g === "A")  return "rgba(0,200,83,0.20)";
  if (g === "B")  return "rgba(41,182,246,0.20)";
  if (g === "C")  return "rgba(255,215,64,0.22)";
  return "rgba(255,255,255,0.10)";
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
export function PostMarketReport({ trades, scorecard, scorecardLoading, scorecardFailed, finalized, reportDate }: {
  trades: Trade[];
  scorecard?: DailyEvidenceScorecard;
  scorecardLoading: boolean;
  scorecardFailed: boolean;
  finalized: boolean;
  reportDate?: string;
}) {
  const closed   = trades.filter(t => t.status === "closed");
  const wins     = closed.filter(t => (t.pnl ?? 0) > 0);
  const losses   = closed.filter(t => (t.pnl ?? 0) <= 0);
  const totalPnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = closed.length ? Math.round((wins.length / closed.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";
  // The report and the letter grade must use the same dated trade ledger.
  // A separately-built evidence tape can contain a different account/date
  // slice, which previously made every historical calendar popup show "F"
  // even when the selected day's trades were profitable.
  const grade = dayGrade(totalPnl);
  const avgWin   = wins.length   ? wins.reduce((s, t) => s + (t.pnl ?? 0), 0) / wins.length   : 0;
  const avgLoss  = losses.length ? losses.reduce((s, t) => s + (t.pnl ?? 0), 0) / losses.length : 0;
  const sessionLabel = reportDate
    ? new Date(`${reportDate}T12:00:00`).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
    : "Today";

  if (closed.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <DailyEvidencePanel data={scorecard} loading={scorecardLoading} failed={scorecardFailed} />
        <div className="card p-8 text-center flex flex-col items-center gap-2">
          <p className="text-3xl">📋</p>
          <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>No completed trades for {sessionLabel}.</p>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>Candidates and order attempts still appear in the evidence review above.</p>
        </div>
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
    ? "A green session is encouraging, but one day does not establish launch readiness."
    : "A red session needs evidence-based review: entry context, fills, and exit timing are separated above.";

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
            {grade.emoji} {finalized ? `Final Grade for ${sessionLabel}` : `Grade So Far for ${sessionLabel}`}: <span style={{ color: pnlColor }}>{grade.letter}</span>
          </p>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{grade.msg}</p>
          <p className="text-xs mt-1" style={{ color: "var(--ink-faint)" }}>
            {closed.length} trade{closed.length !== 1 ? "s" : ""} · {wins.length}W / {losses.length}L · {winRate}% win rate · Net{" "}
            <strong style={{ color: pnlColor }}>{fmt(totalPnl)}</strong>
          </p>
          <p className="text-[10px] mt-1" style={{ color: "var(--ink-faint)" }}>
            This letter is based on the completed trades shown for this date.
          </p>
          {!finalized && (
            <p className="text-[10px] mt-1 font-semibold" style={{ color: "#d97706" }}>
              Live snapshot — this grade is provisional until the market closes at 4:00 p.m. ET.
            </p>
          )}
        </div>
      </div>

      <DailyEvidencePanel data={scorecard} loading={scorecardLoading} failed={scorecardFailed} />

      {/* Plain-English summary */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--ink)" }}>📖 What Happened Today — In Plain English</h3>
        <p className="text-sm leading-relaxed" style={{ color: "var(--ink-muted)" }}>
          On {sessionLabel}, the bot took <strong>{closed.length} trade{closed.length !== 1 ? "s" : ""}</strong>, {perfDesc}.
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
            ? `The bot won more trades than it lost today. That only becomes meaningful when gross wins remain larger than gross losses after costs across many independent sessions.`
            : losses.length > wins.length
            ? `More losses than wins today. Compare profit factor, exact missed setups, entry fills, and replay coverage before deciding what needs to change.`
            : `The win/loss count was even. Profit factor and after-cost expectancy tell us more than the count alone.`
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
          title="How closely today's market matches this strategy. This is not a win promise."
          style={{ background: gradeBg(pm.grade), color: gradeColor(pm.grade), border: `1px solid ${gradeColor(pm.grade)}50` }}
        >
          Match {pm.readiness_score}/100
        </div>
        <span className="text-xl font-bold" style={{ color: "var(--ink)" }}>{pm.ticker}</span>
        <span className="num text-base font-semibold" style={{ color: "var(--ink-muted)" }}>${pm.price.toFixed(2)}</span>
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded-full"
          style={{ color: dirColor, background: "var(--muted)" }}
        >
          <Tooltip text={GLOSSARY.Direction}>Leaning: {dirLabel}</Tooltip>
        </span>
        <span className={`badge ${pm.tradeable_today ? "badge-green" : "badge-blue"}`}>
          {pm.tradeable_today ? "Can trade" : "Research only"}
        </span>
        <span
          className="num text-sm font-semibold ml-auto"
          style={{ color: pm.gap_pct >= 0 ? "var(--positive)" : "var(--negative)" }}
        >
          {pm.gap_pct >= 0 ? "+" : ""}{pm.gap_pct.toFixed(2)}% gap
        </span>
      </div>

      {/* The five real timeframes requested for the morning decision. */}
      <div className="grid grid-cols-5 gap-1.5" aria-label="Market direction by timeframe">
        {(pm.timeframes ?? []).map(frame => {
          const color = frame.bias === "up" ? "var(--positive)" : frame.bias === "down" ? "var(--negative)" : "var(--ink-muted)";
          return <div key={frame.label} className="rounded-md px-2 py-1.5 text-center" style={{ background: "var(--muted)" }}>
            <div className="text-[9px] uppercase tracking-wide text-ink-faint">{{ Minute: "Now (1 min)", Hour: "Short (1 hr)", Day: "Today", Week: "Week", Month: "Month" }[frame.label] ?? frame.label}</div>
            <div className="text-xs font-semibold" style={{ color }}>
              {frame.bias === "unavailable" ? "—" : `${frame.bias === "up" ? "↑" : frame.bias === "down" ? "↓" : "→"} ${frame.change_pct?.toFixed(1)}%`}
            </div>
          </div>;
        })}
      </div>

      {pm.best_strategy && <div className="rounded-md px-3 py-2.5" style={{ background: "var(--accent-subtle)", borderLeft: "3px solid var(--accent)" }}>
        <div className="text-[9px] uppercase tracking-wide text-ink-faint">Best fit today</div>
        <div className="text-sm font-semibold">{pm.best_strategy.name} · match {pm.best_strategy.readiness_score}/100</div>
        <p className="text-xs text-ink-muted mt-1">{pm.best_strategy.reason}</p>
        {pm.strategy_matches.length > 1 && <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-ink-muted">See other fits</summary>
          <div className="pt-2 flex flex-col gap-1">
            {pm.strategy_matches.slice(1).map(match => <div key={match.strategy_id} className="flex justify-between gap-3">
              <span>{match.name}</span><span className="num">{match.readiness_score}/100 · {match.can_trade ? "orders on" : "testing"}</span>
            </div>)}
          </div>
        </details>}
      </div>}

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-1.5">
        {([
          { label: "Volume now",        tip: GLOSSARY.RVOL,    value: `${pm.rvol.toFixed(2)}×`,   color: pm.rvol >= 2 ? "var(--positive)" : pm.rvol >= 1.5 ? "#ffd740" : "var(--ink)" },
          { label: "Usual daily move",  tip: GLOSSARY.ATR,     value: `$${pm.atr.toFixed(2)}`,     color: "var(--ink)" },
          { label: "Usual move %",      tip: GLOSSARY["ATR%"], value: `${pm.atr_pct.toFixed(2)}%`, color: "var(--ink)" },
          { label: "Yesterday close",   tip: "",               value: `$${pm.prev_close.toFixed(2)}`, color: "var(--ink-muted)" },
          { label: "Yesterday high",    tip: "",               value: `$${pm.prev_high.toFixed(2)}`,  color: "var(--positive)" },
          { label: "Yesterday low",     tip: "",               value: `$${pm.prev_low.toFixed(2)}`,   color: "var(--negative)" },
        ] as {label:string;tip:string;value:string;color:string}[]).map(s => (
          <div key={s.label} className="rounded-md px-2 py-1.5 flex flex-col" style={{ background: "var(--muted)" }}>
            <span className="text-[9px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>
              {s.tip ? <Tooltip text={s.tip}>{s.label}</Tooltip> : s.label}
            </span>
            <span className="text-xs num font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Price position bar: prev_low ←→ prev_high with close tick + current price dot */}
      <div className="rounded-md px-3 py-2.5" style={{ background: "var(--muted)" }}>
        <div className="flex justify-between text-[9px] mb-1.5" style={{ color: "var(--ink-faint)" }}>
          <span>▼ ${pm.prev_low.toFixed(2)}</span>
          <span>Yesterday: low to high</span>
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
          📋 {pm.tradeable_today ? "Today's plan" : "What the bot is testing"}
        </div>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>🎯 What must happen:</span> {pm.entry_note}
        </p>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>🛑 Get out if:</span> {pm.stop_note}
        </p>
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          <span className="font-semibold" style={{ color: "var(--ink)" }}>💰 Profit plan:</span> {pm.target_note}
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

  const {
    data: dailyScorecard,
    isLoading: dailyScorecardLoading,
    isError: dailyScorecardFailed,
  } = useQuery({
    queryKey: ["daily-evidence-scorecard", "paper"],
    queryFn: () => api.strategyHealth.dailyScorecard("paper"),
    refetchInterval: 30_000,
  });

  // Rich premarket endpoint — includes ALL watchlist tickers with live Alpaca + yfinance data
  const { data: premarket = [], isLoading: pmLoading } = useQuery<PremarketTicker[]>({
    queryKey: ["premarket"],
    queryFn:  () => api.market.premarket(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const pmMap = useMemo(
    () => new Map<string, PremarketTicker>(premarket.map(p => [p.ticker, p])),
    [premarket],
  );
  const dayOutlook = useMemo(() => premarketDayOutlook(premarket), [premarket]);

  // Only show tickers with a complete pre-market report. Scanner-only names
  // are not useful here because they have no plan, levels, or timeframe read.
  const pmTickers = useMemo(() => premarket.map(p => p.ticker), [premarket]);
  const allTickers = pmTickers;

  const [selected, setSelected]   = useState<string>("");
  const [briefTab, setBriefTab]   = useState<"premarket" | "postmarket">(
    isTradingDayFinal() ? "postmarket" : "premarket"
  );
  useEffect(() => {
    const next = preferredDailyBriefTicker({
      selected,
      loading: pmLoading,
      premarketTickers: pmTickers,
    });
    if (next !== selected) setSelected(next);
  }, [
    selected,
    pmLoading,
    pmTickers,
  ]);

  // Today's trades
  const _now = new Date();
  const sessionFinal = isTradingDayFinal(_now);
  const tradingDate = newYorkDateKey(_now);
  const todayTrades: Trade[] = (tradesResp?.trades ?? []).filter(
    (t) => t.entry_time && newYorkDateKey(t.entry_time) === tradingDate
  );
  const wins     = todayTrades.filter((t) => (t.pnl ?? 0) > 0).length;
  const losses   = todayTrades.filter((t) => (t.pnl ?? 0) < 0).length;
  const totalPnl = todayTrades.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winRate  = todayTrades.length ? Math.round((wins / todayTrades.length) * 100) : 0;
  const pnlColor = totalPnl >= 0 ? "var(--positive)" : "var(--negative)";
  const accountChange = status?.session_pnl ?? 0;
  const accountBotGap = accountChange - totalPnl;

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
  return (
    <>
    <div className="p-4 flex flex-col gap-4 max-w-4xl">

      {/* Header */}
      <div>
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Daily Brief</h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>{today()}</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Account Change",  value: fmt(accountChange),                            color: accountChange >= 0 ? "var(--positive)" : "var(--negative)" },
          { label: "Bot Closed P&L",  value: fmt(totalPnl),                                 color: pnlColor },
          { label: "Today's Trades",  value: String(todayTrades.length),                       color: "var(--ink)" },
          { label: "Account Balance", value: `$${(status?.account_balance ?? 0).toFixed(2)}`, color: "var(--ink)" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-3 flex flex-col gap-0.5">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num text-xl font-semibold" style={{ color: s.color }}>{s.value}</span>
          </div>
        ))}
      </div>

      {Math.abs(accountBotGap) > 1 && (
        <div role="status" className="rounded-md px-3 py-2 text-xs" style={{ background: "var(--muted)", color: "var(--ink-muted)" }}>
          <strong style={{ color: "var(--ink)" }}>Why these totals differ:</strong>{" "}
          Account Change is total broker equity versus the day open; Bot Closed P&L includes only completed bot trades recorded today.
          {" "}Current difference: <strong>{fmt(accountBotGap)}</strong>.
        </div>
      )}

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
            <div className="px-4 py-3 border-b flex items-start justify-between gap-3" style={{ borderColor: "var(--border)" }}>
              <div>
                <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>🏟️ Daily Market Report</h3>
                <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                  Best matches first, from 100 down. The score shows fit—not a promised win.
                </p>
                <details className="mt-1">
                  <summary className="text-[10px] cursor-pointer" style={{ color: "var(--accent)" }}>How the score works</summary>
                  <p className="text-[10px] mt-1 max-w-xl leading-relaxed" style={{ color: "var(--ink-faint)" }}>
                    Each strategy starts with 30–48 points. It gets 7 points for every agreeing minute, hour, day, week, or month view; up to 15 for volume; and extra points when its own rule is present, such as NR7, an inside day, or KER above 0.60. The score stops at 100. It measures setup fit—not win probability.
                  </p>
                </details>
              </div>
              {pmLoading && (
                <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: "var(--muted)", color: "var(--ink-faint)" }}>
                  Loading…
                </span>
              )}
            </div>

            <div
              className="mx-3 mt-3 rounded-xl border px-3 py-2.5 flex items-start gap-3"
              style={{
                borderColor: dayOutlook.level === "green" ? "var(--positive)" : dayOutlook.level === "red" ? "var(--negative)" : dayOutlook.level === "yellow" ? "var(--warning)" : "var(--border)",
                background: dayOutlook.level === "green" ? "var(--positive-bg)" : dayOutlook.level === "red" ? "var(--negative-bg)" : "var(--muted)",
              }}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-xs font-black tracking-wide" style={{ color: "var(--ink)" }}>TODAY'S TRADING OUTLOOK</span>
                  <span className="text-[10px] font-bold" style={{ color: dayOutlook.level === "green" ? "var(--positive)" : dayOutlook.level === "red" ? "var(--negative)" : dayOutlook.level === "yellow" ? "var(--warning)" : "var(--ink-muted)" }}>
                    {dayOutlook.label}
                  </span>
                </div>
                <p className="text-xs font-semibold mt-0.5" style={{ color: "var(--ink)" }}>{dayOutlook.summary}</p>
                <p className="text-[10px] mt-0.5" style={{ color: "var(--ink-muted)" }}>{dayOutlook.detail}</p>
                <p className="text-[10px] mt-1" style={{ color: "var(--ink-faint)" }}>
                  Based only on {dayOutlook.tradableCount} ticker{dayOutlook.tradableCount === 1 ? "" : "s"} the bot may trade. This rates trade conditions—not market direction.
                </p>
              </div>
            </div>

            {allTickers.length === 0 ? (
              <div className="px-4 py-8 text-sm text-center" style={{ color: "var(--ink-muted)" }}>
                No market report is available yet.
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
                    const isActive = ticker === selected;
                    const chg      = pm?.gap_pct ?? 0;
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
                        <div
                          className="text-[9px] font-black rounded px-1 py-0.5 shrink-0"
                          style={{ background: pm?.tradeable_today ? "var(--positive-bg)" : "var(--accent-subtle)", color: pm?.tradeable_today ? "var(--positive)" : "var(--accent)", minWidth: 28, textAlign: "center" }}
                        >
                          {pm?.readiness_score}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-xs font-bold truncate" style={{ color: "var(--ink)" }}>{ticker}</div>
                          <div
                            className="text-[10px] num font-semibold"
                            style={{ color: pm ? chgColor : "var(--ink-faint)" }}
                          >
                            {pm ? `${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%` : "no data"}
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
                  ) : (
                    <p className="text-sm" style={{ color: "var(--ink-muted)" }}>This ticker does not have a complete morning report, so it was removed from the list.</p>
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
          <PostMarketReport
            trades={todayTrades}
            scorecard={dailyScorecard}
            scorecardLoading={dailyScorecardLoading}
            scorecardFailed={dailyScorecardFailed}
            finalized={sessionFinal}
          />

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

    </>
  );
}
