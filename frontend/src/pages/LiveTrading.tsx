/**
 * LiveTrading.tsx — Main trading cockpit.
 * Real-time chart, signal alert banner (Bot Focus), open positions, eval log, scanner.
 */
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Radio, Bot } from "lucide-react";
import { BoomerangReplay, type BoomerangReplayHandle } from "../components/charts/BoomerangReplay";
import { useBotStore } from "../store/bot";
import { useUIStore } from "../store/ui";
import {
  api, type Trade, type OptionsChainRow, type ChartAnnotation, type NewsArticle,
} from "../lib/api";

const FALLBACK_TICKERS = ["SPY", "QQQ"];

type Period = "1D" | "5D" | "1M" | "3M";

// PERIOD_MS was used by KChart for windowing; TradingChart handles it internally

function barLimitForPeriod(tf: string, period: Period): number {
  const barsPerDay: Record<string, number> = {
    "1Min": 420, "5Min": 90, "15Min": 30, "1Hour": 8,
  };
  // FIX 2026-07-17: "1D" was loading 3 trading days of bars (not 1) — the
  // multiplier below was 3, so selecting "1D" actually rendered 7/15, 7/16,
  // AND 7/17 together, which is also what made the swing HH/LH/LL labels look
  // packed/illegible (3x the bars in view = 3x the detected pivots).
  const tradingDays: Record<Period, number> = {
    "1D": 1, "5D": 8, "1M": 25, "3M": 70,
  };
  return Math.min(2000, Math.max(40, Math.ceil((barsPerDay[tf] ?? 90) * (tradingDays[period] ?? 3))));
}

// 2026-07-28: real pipeline order (router_gates.py, then trading/entry.py) —
// used to turn one reason_code into an ordered chip list: every gate BEFORE
// the one that fired gets a green chip (the signal genuinely passed it to
// get this far), the firing gate gets red, and gates AFTER it are omitted
// entirely (never reached — showing them either way would be a guess).
// Some reason_codes share one chip on purpose (over-budget/illiquid/no-data
// are all "couldn't get a tradeable contract" — the Budget chip), matching
// the "simple, not one label per micro-check" request.
const GATE_ORDER: { codes: string[]; label: string }[] = [
  { codes: ["regime_gate"], label: "Regime" },
  { codes: ["grade_filter"], label: "Grade" },
  { codes: ["directional_consensus"], label: "Consensus" },
  { codes: ["confidence_floor"], label: "Confidence" },
  { codes: ["conflict_veto"], label: "Conflict" },
  { codes: ["volume_roc_veto"], label: "Volume" },
  { codes: ["macro_vwap_veto"], label: "Macro VWAP" },
  { codes: ["budget", "illiquid_contract", "no_option_data", "no_liquid_contracts"], label: "Budget" },
  { codes: ["zero_contracts"], label: "Sizing" },
  { codes: ["spread_too_wide"], label: "Spread" },
  { codes: ["rr_too_low"], label: "R:R" },
  { codes: ["ai_decision_veto"], label: "AI review" },
];

function buildGateChips(outcome: string, reasonCode: string | null): { label: string; passed: boolean }[] {
  const firedIdx = reasonCode ? GATE_ORDER.findIndex((g) => g.codes.includes(reasonCode)) : -1;
  const upTo = outcome === "entered" ? GATE_ORDER.length : (firedIdx === -1 ? 0 : firedIdx + 1);
  const chips = GATE_ORDER.slice(0, upTo).map((g, i) => ({
    label: g.label,
    passed: outcome === "entered" || i < firedIdx,
  }));
  if (outcome === "entered") chips.push({ label: "Entered", passed: true });
  return chips;
}

function isSeparator(entry: Record<string, unknown>): boolean {
  return !!entry["_separator"];
}

function isNetworkLog(entry: { module?: string; message?: string; level?: string; [key: string]: unknown }): boolean {
  const mod = (entry.module_name ?? entry.module ?? "").toString().toLowerCase();
  const msg = (entry.message ?? "").toString().toLowerCase();
  if (mod.includes("broker") || mod.includes("alpaca") || mod.includes("tradier")) return true;
  if (msg.includes("http") || msg.includes("timeout") || msg.includes("connection")
    || msg.includes("socket") || msg.includes("request") || msg.includes("retry")
    || msg.includes("yfinance") || msg.includes("ssl")
    || msg.includes("get_bars") || msg.includes("get_session_bars")
    || msg.includes("session_bars") || msg.includes("bars for 20")
    || msg.includes("get_account") || msg.includes("get_snapshot")
    || msg.includes("circuit breaker") || msg.includes("network")
    || msg.includes("backfill") || msg.includes("database initialised")
    || msg.includes("initialised at /") || msg.includes("synced")
    || msg.includes("alpaca_get_failed") || msg.includes("extended_live")) return true;
  return false;
}

function PnlBadge({ value }: { value?: number }) {
  if (value == null) return <span className="text-ink-muted">—</span>;
  return (
    <span style={{ color: value >= 0 ? "var(--positive)" : "var(--negative)" }}>
      {value >= 0 ? "+" : ""}${value.toFixed(2)}
    </span>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function fmtExp(e: string): string {
  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const p = e?.split("-");
  if (!p || p.length < 3) return e ?? "";
  const mo  = parseInt(p[1], 10) - 1;
  const day = parseInt(p[2], 10);
  return `${MONTHS[mo] ?? p[1]} ${day}`;
}

function toDiscordStr(ev: any): string {
  const dir = (ev.opt_type ?? "").toUpperCase();
  const stk = ev.strike != null
    ? `$${ev.strike % 1 === 0 ? ev.strike.toFixed(0) : ev.strike.toFixed(2)}`
    : "";
  const exp = ev.expiry ? fmtExp(ev.expiry) : "";
  const nc  = ev.contracts ?? 1;
  const ent = ev.eff_entry != null ? `$${ev.eff_entry.toFixed(2)}` : "";
  const tgt = ev.s1_target != null ? `$${ev.s1_target.toFixed(2)}` : "";
  const pnl = ev.profit    != null ? `+$${ev.profit.toFixed(2)}`   : "";
  const sid = ev.strategy  ?? "";
  return `[${dir}] ${ev.ticker ?? ""} ${stk} ${exp} | ${nc}c @ ${ent} → ${tgt} (${pnl}) [${sid}]`;
}

export function LiveTrading() {
  const [ticker,          setTicker]          = useState("SPY");
  const [tf,              setTf]              = useState("5Min");
  const [period,          setPeriod]          = useState<Period>("1D");
  const [showVwap,        setShowVwap]        = useState(true);
  const [showVwapBands,   setShowVwapBands]   = useState(true);
  const [showOR,          setShowOR]          = useState(true);
  const [showSwings,      setShowSwings]      = useState(true);
  const [showPositionCard,setShowPositionCard]= useState(true);
  const [scannerTab,      setScannerTab]      = useState<"scanner" | "chain">("scanner");
  // 2026-07-31: "Board" replaces the old standalone Watching tab — a
  // per-ticker view (trading/watching/blocked) that also absorbs INST_ORB's
  // mid-retest data, so there's one place to check a ticker instead of
  // cross-referencing this tab against the Thinking feed. "Log" is the
  // unchanged old Thinking/Network content, just no longer the default.
  const [mainPanelTab,    setMainPanelTab]    = useState<"board" | "log">("board");
  const [boardTicker,     setBoardTicker]     = useState("");
  const [logPaused,       setLogPaused]       = useState(false);
  const logSnapshotRef  = useRef<typeof logs>([]);
  const [logTab,         setLogTab]           = useState<"thinking" | "network">("thinking");
  const [logRawTicker,   setLogRawTicker]     = useState("");
  const [tradeDrawerId,  setTradeDrawerId]    = useState<number | null>(null);
  const chartReplayRef  = useRef<BoomerangReplayHandle>(null);

  const { status, logs } = useBotStore();
  const { } = useUIStore();

  // "Watch this setup" — jump the chart's scrub position to just before a
  // Signal History / Bot Focus entry and auto-play from there (chart refactor
  // Phase 3). Eval log entries only carry a display-only "HH:MM:SS" string
  // (no date), but every entry is from today on this live cockpit, so
  // today's date + that time gives a real timestamp the replay can seek to.
  function watchAt(ts?: string) {
    if (!ts) return;
    const todayStr = new Date().toISOString().slice(0, 10);
    chartReplayRef.current?.jumpToTime(`${todayStr}T${ts}`);
  }

  const barsRefetchMs = tf === "1Min" ? 15_000 : tf === "5Min" ? 30_000 : 60_000;

  // ── Data queries ────────────────────────────────────────────────────────────
  // 1-minute bars: yfinance only reliably serves ~1 trading day.
  // Requesting 5D/1M/3M of 1-minute data makes the API fail, which triggers
  // an unhandled promise rejection → React error boundary → red outline on chart.
  // Cap to 1D silently when the user picks 1m.
  const effectivePeriod: Period = tf === "1Min" && period !== "1D" ? "1D" : period;

  const { data: bars = [], isLoading: barsLoading } = useQuery({
    queryKey: ["bars", ticker, tf, effectivePeriod],
    queryFn: () => api.market.bars(ticker, tf, barLimitForPeriod(tf, effectivePeriod)),
    refetchInterval: barsRefetchMs,
    retry: false,   // fail fast — retries pile up and delay visible feedback
  });

  const { data: openTrades = [] } = useQuery({
    queryKey: ["open-trades"],
    queryFn: api.trades.open,
    refetchInterval: 5_000,
  });

  const { data: todayTradesRaw = [] } = useQuery({
    queryKey: ["today-trades"],
    queryFn: () => api.trades.list("paper", "all"),
    refetchInterval: 10_000,
    select: (res: any) => {
      // Use local-date comparison — ET tz-naive timestamps don't match toISOString() (UTC)
      // after ~8 PM ET when UTC has already rolled to the next day.
      const now = new Date();
      return (res?.trades ?? []).filter((t: Trade) =>
        t.entry_time != null && new Date(t.entry_time).toDateString() === now.toDateString()
      );
    },
  });

  const { data: scanner = [] } = useQuery({
    queryKey: ["scanner"],
    queryFn: api.market.scanner,
    refetchInterval: 60_000,
  });

  const { data: or } = useQuery({
    queryKey: ["or", ticker],
    queryFn: () => api.market.or(ticker),
    enabled: showOR,
    refetchInterval: 300_000,
  });

  const { data: chain = [] } = useQuery({
    queryKey: ["chain", ticker],
    queryFn:  () => api.market.chain(ticker),
    enabled:  scannerTab === "chain",
    refetchInterval: 60_000,
    retry: false,
  });

  // "Board" — one row per ticker, current state only (trading/watching/
  // blocked). See api/routes/tickers.py::get_board() — merges open
  // positions, INST_ORB's retest state, and today's signal journal so this
  // can never disagree with the Open Positions table or the Log tab; same
  // underlying sources, just indexed by ticker instead of by event.
  const { data: boardData } = useQuery({
    queryKey: ["ticker-board"],
    queryFn:  api.tickers.board,
    refetchInterval: 15_000,
    retry: false,
  });
  const boardRows = boardData?.tickers ?? [];
  const boardActiveCount = boardRows.filter((r) => r.status !== "blocked").length;

  // Bot chart annotations — zones, hlines, markers emitted by strategy_router
  const { data: annotations = [] } = useQuery<ChartAnnotation[]>({
    queryKey: ["annotations", ticker],
    queryFn:  () => api.bot.annotations(ticker),
    refetchInterval: 5_000,   // same cadence as bot tick
    retry: false,
  });

  // News — Alpaca's free news API, refreshed every 5 minutes
  const newsSymbols = useMemo(() => {
    const syms = [ticker, ...openTrades.map((t: Trade) => t.ticker)];
    return [...new Set(syms)].slice(0, 5).join(",");
  }, [ticker, openTrades]);

  const { data: newsArticles = [] } = useQuery<NewsArticle[]>({
    queryKey: ["news", newsSymbols],
    queryFn:  () => api.market.news(newsSymbols, 15),
    refetchInterval: 5 * 60_000,   // refresh every 5 minutes
    retry: false,
  });

  // Trade log drawer — fetches system_events filtered to clicked trade's ticker+entry_time
  const { data: tradeEvents = [] } = useQuery({
    queryKey: ["trade-events", tradeDrawerId],
    queryFn: () => api.bot.tradeEvents(tradeDrawerId!),
    enabled: tradeDrawerId !== null,
    refetchInterval: 5_000,
  });

  // ── Derived values ──────────────────────────────────────────────────────────
  const dropdownTickers = useMemo(() => {
    const base   = scanner.length > 0 ? scanner.map((s: any) => s.ticker) : FALLBACK_TICKERS;
    const extra  = ["SPY", "QQQ", ...openTrades.map((t: Trade) => t.ticker)];
    return [...new Set([...base, ...extra])];
  }, [scanner, openTrades]);

  const tickerTrades      = (todayTradesRaw as Trade[]).filter((t: Trade) => t.ticker === ticker);
  const openTickerTrade   = tickerTrades.find((t: Trade) => !t.exit_time);
  const positionLevels    = openTickerTrade ? {
    entry:     openTickerTrade.entry_price  ?? undefined,
    stop:      openTickerTrade.stop_price   ?? undefined,
    target:    openTickerTrade.target_price ?? undefined,
    trail:     (openTickerTrade as any).trail_price ?? undefined,
    direction: (openTickerTrade.direction === "short" ? "short" : "long") as "long" | "short",
    contracts: openTickerTrade.contracts    ?? undefined,
  } : undefined;

  // Narration for the boomerang replay's caption strip — reuses the same
  // trade-events endpoint the trade drawer already uses, scoped to whichever
  // trade is currently open on this ticker (if any). No new backend endpoint.
  const { data: narrationEvents = [] } = useQuery({
    queryKey: ["trade-narration", openTickerTrade?.id],
    queryFn: () => api.bot.tradeEvents(openTickerTrade!.id),
    enabled: openTickerTrade != null,
    refetchInterval: 5_000,
    select: (rows) => rows.map((r) => ({ ts: r.ts, message: r.message })),
  });

  const lastClose = bars[bars.length - 1]?.close ?? 0;
  const orHighRaw  = or?.high ?? 0;
  const orLowRaw   = or?.low  ?? 0;
  const orInRange  = lastClose > 0 && orHighRaw > 0 && orLowRaw > 0
    && Math.abs(orHighRaw - lastClose) / lastClose < 0.15
    && Math.abs(orLowRaw  - lastClose) / lastClose < 0.15;
  const safeOrHigh = orInRange ? orHighRaw : undefined;
  const safeOrLow  = orInRange ? orLowRaw  : undefined;

  // FIX 2026-07-17: "no_signal" (no setup found at all) used to render as a
  // compact-but-still-visible "SKIP · no setup" row. That's the single most
  // common evaluation outcome (most bars have no setup), so it drowned out
  // the genuinely informative skip reasons (low confidence, spread too wide,
  // R:R too low, etc.) — dropped entirely per explicit ask instead of just
  // compacted.
  const evalLog: any[] = ((status as any)?.eval_log ?? [])
    .filter((ev: any) => !(ev.rejected && ev.reason === "no_signal"));
  const latestSignal    = evalLog[0] ?? null;
  const scannerColor    = (changePct: number) =>
    changePct >= 0 ? "var(--positive)" : "var(--negative)";

  return (
    <>
    <div className="p-4 flex flex-col gap-4">

      {/* ── Stat bar ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap sm:gap-3 items-start">
        {[
          { label: "Balance",     value: `$${(status?.account_balance ?? 0).toFixed(2)}` },
          { label: "Day Open",    value: `$${(status?.day_start_balance ?? status?.account_balance ?? 0).toFixed(2)}` },
          { label: "Session P&L", value: (
            <span className="flex items-center gap-1.5 flex-wrap">
              <PnlBadge value={status?.session_pnl} />
              <span
                className="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide"
                style={{
                  background: status?.is_paper !== false
                    ? "rgba(234, 148, 29, 0.15)"
                    : "rgba(34, 197, 94, 0.15)",
                  color: status?.is_paper !== false ? "#ea941d" : "#22c55e",
                  border: `1px solid ${status?.is_paper !== false ? "#ea941d55" : "#22c55e55"}`,
                }}
              >
                {status?.is_paper !== false ? "Paper" : "Live"}
              </span>
            </span>
          )},
          { label: "Opt BP",  value: `$${(status?.options_buying_power ?? 0).toFixed(2)}` },
          { label: "Open",    value: openTrades.length },
          { label: "Signal",  value: status?.last_strategy_id ?? "—" },
          { label: "Mode",    value: status?.mode ? (status.mode as string).toUpperCase() : "—" },
        ].map((s) => (
          <div key={s.label} className="card px-4 py-2.5 flex flex-col gap-0.5 min-w-[110px]">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{s.label}</span>
            <span className="num font-semibold text-sm" style={{ color: "var(--ink)" }}>
              {s.value}
            </span>
          </div>
        ))}

      </div>

      {/* ── Bot Focus — Signal Alert Banner ───────────────────────────────── */}
      {/* Shows the most recent signal prominently. Orange border = manual (enter yourself).
          Green border = auto-executed. Always visible so you never miss a signal. */}
      <div
        className="card px-4 py-3"
        style={{
          borderLeft: latestSignal
            ? `4px solid ${latestSignal.mode === "signal" ? "var(--warning)" : "var(--positive)"}`
            : "4px solid var(--border)",
        }}
      >
        {/* Header row */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {latestSignal?.mode === "signal"
              ? <Radio size={14} style={{ color: "var(--warning)" }} />
              : <Bot   size={14} style={{ color: latestSignal ? "var(--positive)" : "var(--ink-faint)" }} />
            }
            <span className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--ink-muted)" }}>
              Bot Focus
            </span>
            {latestSignal && (
              <span
                className="text-[10px] font-bold px-2 py-0.5 rounded uppercase"
                style={{
                  background: latestSignal.mode === "signal"
                    ? "rgba(234,148,29,0.15)" : "rgba(34,197,94,0.15)",
                  color: latestSignal.mode === "signal" ? "var(--warning)" : "var(--positive)",
                }}
              >
                {latestSignal.mode === "signal" ? "📡 Enter Manually" : "✅ Auto-Executed"}
              </span>
            )}
          </div>
          {latestSignal && (
            <span className="text-[10px] flex items-center gap-2" style={{ color: "var(--ink-faint)" }}>
              {latestSignal.ts}  ·  tap row to copy
              <button
                className="btn btn-ghost btn-sm"
                style={{ padding: "1px 6px", fontSize: 9 }}
                title="Watch this setup on the chart"
                onClick={(e) => { e.stopPropagation(); watchAt(latestSignal.ts); }}
              >
                ▶ Watch
              </button>
            </span>
          )}
        </div>

        {/* Signal content */}
        {!latestSignal ? (
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
            {status?.running
              ? `Scanning ${(status as any)?.current_ticker ?? "…"} — no signals yet`
              : "Start the bot to begin scanning"}
          </p>
        ) : (() => {
          const isCall = (latestSignal.opt_type ?? "").toLowerCase() === "call";
          const stk    = latestSignal.strike != null
            ? `$${latestSignal.strike % 1 === 0
                ? latestSignal.strike.toFixed(0)
                : latestSignal.strike.toFixed(2)}`
            : "";
          return (
            <button
              className="w-full text-left"
              title="Click to copy Discord-ready trade idea"
              onClick={() => navigator.clipboard.writeText(toDiscordStr(latestSignal)).catch(() => {})}
            >
              <div className="flex flex-wrap items-center gap-3">
                {/* Direction badge */}
                <span style={{
                  fontSize: 18, fontWeight: 800, padding: "2px 10px", borderRadius: 4,
                  background: isCall ? "rgba(0,200,100,0.15)" : "rgba(255,80,80,0.15)",
                  color: isCall ? "var(--positive)" : "var(--negative)",
                  fontFamily: "JetBrains Mono, monospace",
                }}>
                  {(latestSignal.opt_type ?? "").toUpperCase()}
                </span>
                {/* Ticker — click to switch chart */}
                <span
                  style={{ fontSize: 20, fontWeight: 800, color: "var(--accent)", cursor: "pointer" }}
                  onClick={(e) => { e.stopPropagation(); setTicker(latestSignal.ticker); }}
                  title={`View ${latestSignal.ticker} chart`}
                >
                  {latestSignal.ticker}
                </span>
                <span style={{ fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>{stk}</span>
                {latestSignal.expiry && (
                  <span style={{ color: "var(--ink-muted)", fontSize: 14 }}>
                    {fmtExp(latestSignal.expiry)}
                  </span>
                )}
                {latestSignal.strategy && (
                  <span className="badge badge-blue">{latestSignal.strategy}</span>
                )}
                {/* Sizing */}
                <div style={{
                  marginLeft: "auto", textAlign: "right",
                  fontFamily: "JetBrains Mono, monospace", fontSize: 13,
                }}>
                  <span style={{ color: "var(--ink)" }}>
                    {latestSignal.contracts ?? 1}c
                  </span>
                  <span style={{ color: "var(--ink-muted)" }}>{" @ "}</span>
                  <span style={{ color: "var(--ink)", fontWeight: 700 }}>
                    ${(latestSignal.eff_entry ?? 0).toFixed(2)}
                  </span>
                  <span style={{ color: "var(--ink-muted)" }}>{" → "}</span>
                  <span style={{ color: "var(--positive)", fontWeight: 700 }}>
                    ${(latestSignal.s1_target ?? 0).toFixed(2)}
                  </span>
                  {latestSignal.profit != null && (
                    <span style={{ color: "var(--positive)", opacity: 0.7, marginLeft: 6 }}>
                      (+${latestSignal.profit.toFixed(2)})
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })()}
      </div>

      {/* ── Main grid: chart + scanner ────────────────────────────────────── */}
      <div className="grid gap-4 chart-scanner-grid">
        {/* Chart panel */}
        <div className="card overflow-hidden">
          <div
            className="flex items-center gap-3 px-3 py-2 border-b text-sm flex-wrap"
            style={{ borderColor: "var(--border)" }}
          >
            <select
              className="select"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
            >
              {dropdownTickers.map((t) => <option key={t}>{t}</option>)}
            </select>
            <div className="flex gap-1">
              {(["1Min","5Min","15Min","1Hour"] as const).map((t) => (
                <button key={t}
                  className={`btn btn-sm ${tf === t ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setTf(t)}>
                  {t.replace("Min","m").replace("Hour","h")}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {(["1D","5D","1M","3M"] as const).map((p) => (
                <button key={p}
                  className={`btn btn-sm ${period === p ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setPeriod(p)}>
                  {p}
                </button>
              ))}
            </div>
            <div className="flex gap-1 ml-1 border-l pl-3" style={{ borderColor: "var(--border)" }}>
              {([
                ["VWAP",   showVwap,        setShowVwap],
                ["Bands",  showVwapBands,   setShowVwapBands],
                ["OR",     showOR,          setShowOR],
                ["Swings", showSwings,      setShowSwings],
                ["Pos",    showPositionCard,setShowPositionCard],
              ] as [string, boolean, (v: boolean) => void][]).map(([label, val, setter]) => (
                <button key={label}
                  className={`btn btn-sm ${val ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setter(!val)}>
                  {label}
                </button>
              ))}
            </div>
            <div className="flex-1" />
            {barsLoading && <RefreshCw size={13} className="animate-spin text-ink-muted" />}
          </div>
          {/* Rebuilt 2026-07-19 on the new single chart engine (TradeChart +
              BoomerangReplay) — replaces the old KChart/ChartReplay pair.
              Native lightweight-charts pan/zoom/timeframe switching (no
              custom wheel/resize workarounds), real shaded zones, and the
              "Watch this setup" boomerang jump-to-time with narration. */}
          <BoomerangReplay
            ref={chartReplayRef}
            mode="live"
            resetKey={`${ticker}|${tf}`}
            bars={bars}
            trades={tickerTrades}
            showVwap={showVwap}
            showVwapBands={showVwapBands}
            showOR={showOR}
            showSwings={showSwings}
            showPositionCard={showPositionCard}
            showRsi
            showMacd
            orHigh={safeOrHigh}
            orLow={safeOrLow}
            positionLevels={positionLevels}
            currentOptionPrice={
              openTickerTrade
                ? (status?.open_positions?.[String(openTickerTrade.id)]?.current_option_price ?? null)
                : null
            }
            ticker={ticker}
            height={500}
            annotations={annotations}
            narrationEvents={narrationEvents}
          />
        </div>

        {/* Scanner / Chain panel — the old Watching tab that used to live
            here moved into the Board tab below (see mainPanelTab), since
            Board covers the same INST_ORB data plus everything else. */}
        <div className="card flex flex-col">
          {/* Tab header */}
          <div className="flex border-b text-xs font-semibold uppercase tracking-wider"
               style={{ borderColor: "var(--border)" }}>
            {(["scanner", "chain"] as const).map((tab) => (
              <button key={tab} onClick={() => setScannerTab(tab)}
                className="px-3 py-2 transition-colors"
                style={{
                  color: scannerTab === tab ? "var(--ink)" : "var(--ink-muted)",
                  borderBottom: scannerTab === tab ? "2px solid var(--accent)" : "2px solid transparent",
                  background: "none",
                }}>
                {tab === "scanner" ? "Premarket Scanner" : `${ticker} Chain`}
              </button>
            ))}
          </div>

          {/* Scanner list */}
          {scannerTab === "scanner" && (
            <div className="overflow-y-auto" style={{ maxHeight: 220 }}>
              {scanner.length === 0 ? (
                <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                  No scan results yet — bot scans 9:00–9:25 ET
                </p>
              ) : (
                scanner.map((s) => (
                  <button key={s.ticker}
                    className="w-full px-3 py-2 flex items-center justify-between hover:bg-muted transition-colors text-left border-b"
                    style={{ borderColor: "var(--border)" }}
                    onClick={() => setTicker(s.ticker)}>
                    <div>
                      <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                        {s.ticker}
                      </div>
                      <div className="text-xs num" style={{ color: "var(--ink-muted)" }}>
                        ${s.price.toFixed(2)} · {s.rvol.toFixed(1)}x RVOL
                      </div>
                    </div>
                    <span className="text-xs num font-medium" style={{ color: scannerColor(s.change_pct) }}>
                      {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                    </span>
                  </button>
                ))
              )}
            </div>
          )}

          {/* Options chain */}
          {scannerTab === "chain" && (
            <div className="overflow-y-auto" style={{ maxHeight: 220 }}>
              {chain.length === 0 ? (
                <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                  No chain data — Tradier key required, or no liquid contracts 7–21 DTE
                </p>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse",
                  fontFamily: "JetBrains Mono, monospace", fontSize: 10 }}>
                  <thead>
                    <tr style={{ background: "var(--surface-raised)" }}>
                      <th colSpan={3} style={{ padding: "4px 6px", color: "var(--positive)",
                        textAlign: "center", borderBottom: "1px solid var(--border)" }}>CALLS</th>
                      <th style={{ padding: "4px 6px", color: "var(--ink-muted)", textAlign: "center",
                        borderBottom: "1px solid var(--border)", borderLeft: "1px solid var(--border)",
                        borderRight: "1px solid var(--border)" }}>Strike</th>
                      <th colSpan={3} style={{ padding: "4px 6px", color: "var(--negative)",
                        textAlign: "center", borderBottom: "1px solid var(--border)" }}>PUTS</th>
                    </tr>
                    <tr style={{ background: "var(--surface-raised)" }}>
                      {["Bid","Mid","Ask"].map((h) => (
                        <th key={`c-${h}`} style={{ padding: "3px 5px", color: "var(--ink-faint)",
                          fontWeight: 500, borderBottom: "1px solid var(--border)", textAlign: "right" }}>{h}</th>
                      ))}
                      <th style={{ padding: "3px 5px", color: "var(--ink-muted)", fontWeight: 700,
                        borderBottom: "1px solid var(--border)", borderLeft: "1px solid var(--border)",
                        borderRight: "1px solid var(--border)", textAlign: "center" }}>—</th>
                      {["Bid","Mid","Ask"].map((h) => (
                        <th key={`p-${h}`} style={{ padding: "3px 5px", color: "var(--ink-faint)",
                          fontWeight: 500, borderBottom: "1px solid var(--border)", textAlign: "right" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(chain as OptionsChainRow[]).map((row) => (
                      <tr key={row.strike} style={{ borderBottom: "1px solid var(--border)" }}>
                        {[row.call_bid, row.call_mid, row.call_ask].map((v, i) => (
                          <td key={i} style={{ padding: "3px 5px", textAlign: "right",
                            color: "var(--positive)" }}>
                            {v != null ? v.toFixed(2) : "—"}
                          </td>
                        ))}
                        <td style={{ padding: "3px 5px", textAlign: "center", fontWeight: 700,
                          color: "var(--ink)", borderLeft: "1px solid var(--border)",
                          borderRight: "1px solid var(--border)", background: "var(--surface-raised)" }}>
                          {row.strike.toFixed(0)}
                        </td>
                        {[row.put_bid, row.put_mid, row.put_ask].map((v, i) => (
                          <td key={i} style={{ padding: "3px 5px", textAlign: "right",
                            color: "var(--negative)" }}>
                            {v != null ? v.toFixed(2) : "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Signal History — all recent evaluations */}
          <div className="border-t px-3 py-2 flex items-center justify-between"
               style={{ borderColor: "var(--border)" }}>
            <span className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--ink-muted)" }}>Signal History</span>
            <span className="text-[9px]" style={{ color: "var(--ink-faint)" }}>tap to copy</span>
          </div>
          <div className="overflow-y-auto flex-1" style={{ minHeight: 200 }}>
            {evalLog.length === 0 ? (
              <p className="text-xs px-3 pb-3" style={{ color: "var(--ink-muted)" }}>
                {status?.running
                  ? "Scanning… no contract evaluations yet"
                  : "Waiting for bot to start scanning…"}
              </p>
            ) : (
              evalLog.map((ev: any, i: number) => {
                // Rejected evaluations (no contract) — compact skip row instead of
                // the meaningless "1c @ $0.00 → $0.00" template.
                if (ev.rejected) {
                  const reasonLabel: Record<string, string> = {
                    no_signal:        "no setup",
                    below_confidence: "low confidence",
                    zero_contracts:   "can't size 1 contract",
                    spread_too_wide:  "spread too wide",
                    rr_too_low:       "R:R too low",
                    macro_vwap_veto:  "macro VWAP conflict",
                  };
                  return (
                    <div key={i}
                      className="w-full px-3 py-1 border-b"
                      style={{ borderColor: "var(--border)", fontFamily: "JetBrains Mono, monospace",
                               fontSize: 10, display: "flex", alignItems: "center", gap: 6,
                               opacity: 0.65 }}>
                      <span style={{ color: "var(--ink-faint)", fontSize: 9, minWidth: 50 }}>{ev.ts ?? ""}</span>
                      <span style={{ color: "var(--ink-muted)", fontWeight: 600 }}>{ev.ticker}</span>
                      <span style={{
                        fontSize: 8, fontWeight: 700, padding: "1px 4px", borderRadius: 2,
                        background: "rgba(139,148,158,0.15)", color: "var(--ink-muted)",
                      }}>SKIP</span>
                      <span style={{ color: "var(--ink-muted)" }}>
                        {reasonLabel[ev.reason] ?? ev.reason}
                        {ev.strategy ? ` · ${ev.strategy}` : ""}
                        {ev.confidence ? ` · conf ${(ev.confidence * 100).toFixed(0)}%` : ""}
                      </span>
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ padding: "0px 5px", fontSize: 8, marginLeft: "auto" }}
                        title="Watch this moment on the chart"
                        onClick={(e) => { e.stopPropagation(); watchAt(ev.ts); }}
                      >
                        ▶
                      </button>
                    </div>
                  );
                }
                const isCall = (ev.opt_type ?? "").toLowerCase() === "call";
                const stk    = ev.strike != null
                  ? `$${ev.strike % 1 === 0 ? ev.strike.toFixed(0) : ev.strike.toFixed(2)}`
                  : "";
                const isSignal = ev.mode === "signal";
                return (
                  <button key={i}
                    className="w-full text-left px-3 py-1.5 border-b hover:bg-muted transition-colors"
                    style={{ borderColor: "var(--border)", fontFamily: "JetBrains Mono, monospace", fontSize: 10 }}
                    title="Click to copy Discord-ready trade idea"
                    onClick={() => navigator.clipboard.writeText(toDiscordStr(ev)).catch(() => {})}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 2 }}>
                      <span style={{ color: "var(--ink-faint)", fontSize: 9, minWidth: 50 }}>{ev.ts ?? ""}</span>
                      <span style={{
                        fontSize: 8, fontWeight: 700, padding: "1px 4px", borderRadius: 2,
                        background: isCall ? "rgba(0,200,100,0.15)" : "rgba(255,80,80,0.15)",
                        color: isCall ? "var(--positive)" : "var(--negative)",
                      }}>
                        {(ev.opt_type ?? "").toUpperCase()}
                      </span>
                      <span style={{ color: "var(--accent)", fontWeight: 700, cursor: "pointer" }}
                        onClick={(e) => { e.stopPropagation(); setTicker(ev.ticker); }}
                        title={`View ${ev.ticker} chart`}>
                        {ev.ticker}
                      </span>
                      <span style={{ color: "var(--ink)" }}>{stk}</span>
                      {ev.expiry && <span style={{ color: "var(--ink-muted)" }}>{fmtExp(ev.expiry)}</span>}
                      {ev.strategy && <span className="badge badge-blue" style={{ fontSize: 7 }}>{ev.strategy}</span>}
                      {/* mode badge */}
                      <span style={{
                        fontSize: 7, fontWeight: 700, padding: "1px 4px", borderRadius: 2, marginLeft: "auto",
                        background: isSignal ? "rgba(234,148,29,0.15)" : "rgba(34,197,94,0.15)",
                        color: isSignal ? "var(--warning)" : "var(--positive)",
                      }}>
                        {isSignal ? "MANUAL" : "AUTO"}
                      </span>
                      {/* Watch this setup — jumps the chart's scrub position to this
                          moment and auto-plays (chart refactor Phase 3). A <span>, not
                          a nested <button>, since this whole row is already a <button>. */}
                      <span
                        role="button"
                        style={{ fontSize: 9, color: "var(--accent)", cursor: "pointer", padding: "0 2px" }}
                        title="Watch this setup on the chart"
                        onClick={(e) => { e.stopPropagation(); watchAt(ev.ts); }}
                      >
                        ▶
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 8, color: "var(--ink-muted)" }}>
                      <span>
                        <span style={{ color: "var(--ink)" }}>{ev.contracts ?? 1}c</span>
                        {" @ "}
                        <span style={{ color: "var(--ink)", fontWeight: 600 }}>${(ev.eff_entry ?? 0).toFixed(2)}</span>
                        {" → "}
                        <span style={{ color: "var(--positive)", fontWeight: 600 }}>${(ev.s1_target ?? 0).toFixed(2)}</span>
                        {ev.profit != null && (
                          <span style={{ color: "var(--positive)", opacity: 0.7 }}>{" "}(+${ev.profit.toFixed(2)})</span>
                        )}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* ── Open positions + eval log ─────────────────────────────────────── */}
      <div className="grid gap-4 two-col-grid">
        {/* Open positions */}
        <div className="card">
          <div className="px-3 py-2 border-b text-xs font-semibold uppercase tracking-wider"
               style={{ borderColor: "var(--border)", color: "var(--ink-muted)" }}>
            Open Positions ({openTrades.length})
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Dir</th><th>Qty</th><th>Entry</th>
                  <th>Now</th><th>Strategy</th><th>P&L (live)</th><th></th>
                </tr>
              </thead>
              <tbody>
                {openTrades.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-6" style={{ color: "var(--ink-muted)" }}>
                      No open positions
                    </td>
                  </tr>
                ) : (
                  openTrades.map((t: Trade) => {
                    const livePos = status?.open_positions?.[String(t.id)];
                    const curPx   = livePos?.current_option_price ?? null;
                    const qty     = livePos?.contracts ?? t.contracts ?? 1;
                    const unreal  = curPx != null ? (curPx - t.entry_price) * qty * 100 : null;
                    const pnlPct  = curPx != null ? (curPx - t.entry_price) / t.entry_price * 100 : null;
                    const updTime = livePos?.current_option_price_time;
                    return (
                      <tr key={t.id}
                        style={{ cursor: "pointer" }}
                        title="Click to view bot thinking log for this trade"
                        onClick={() => setTradeDrawerId(id => id === t.id ? null : t.id)}>
                        <td className="font-semibold"
                          style={{ color: "var(--accent)" }}
                          onClick={(e) => { e.stopPropagation(); setTicker(t.ticker); }}
                          title={`View ${t.ticker} chart`}>
                          {t.ticker}
                        </td>
                        <td>
                          <span className={`badge ${t.direction === "long" ? "badge-green" : "badge-red"}`}>
                            {t.direction?.toUpperCase()}
                          </span>
                        </td>
                        <td className="num text-center">
                          <span className="badge badge-blue">{qty}c</span>
                        </td>
                        <td className="num">${t.entry_price.toFixed(2)}</td>
                        <td className="num" style={{ whiteSpace: "nowrap" }}>
                          {curPx != null ? (
                            <>
                              <span style={{ fontWeight: 600 }}>${curPx.toFixed(2)}</span>
                              {updTime && (
                                <span style={{ color: "var(--ink-faint)", fontSize: 9, marginLeft: 3 }}>
                                  {updTime}
                                </span>
                              )}
                            </>
                          ) : "—"}
                        </td>
                        <td className="text-xs" style={{ color: "var(--ink-muted)" }}>
                          {t.strategy_id ?? "—"}
                        </td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          {unreal != null ? (
                            <span style={{ fontWeight: 700, color: unreal >= 0 ? "var(--positive)" : "var(--negative)" }}>
                              {unreal >= 0 ? "+" : ""}${unreal.toFixed(2)}
                              <span style={{ fontSize: 10, marginLeft: 4, opacity: 0.75, fontWeight: 400 }}>
                                ({pnlPct != null ? (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(1) + "%" : ""})
                              </span>
                            </span>
                          ) : (
                            <PnlBadge value={t.pnl} />
                          )}
                        </td>
                        <td>
                          <button className="btn btn-ghost btn-sm text-xs"
                            onClick={() => api.bot.closeTrade(t.id)}>
                            Close
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Board / Log — Board is the default per-ticker view (see
            boardData above); Log is the old Thinking/Network scrolling feed,
            unchanged, just no longer the first thing you see. */}
        <div className="flex border-b text-xs font-semibold uppercase tracking-wider"
             style={{ borderColor: "var(--border)" }}>
          {(["board", "log"] as const).map((tab) => (
            <button key={tab} onClick={() => setMainPanelTab(tab)}
              className="px-3 py-2 transition-colors"
              style={{
                color: mainPanelTab === tab ? "var(--ink)" : "var(--ink-muted)",
                borderBottom: mainPanelTab === tab ? "2px solid var(--accent)" : "2px solid transparent",
                background: "none",
              }}>
              {tab === "board" ? `Board${boardActiveCount ? ` (${boardActiveCount})` : ""}` : "Log"}
            </button>
          ))}
        </div>

        {mainPanelTab === "board" && (
          <div className="card flex flex-col">
            <div className="p-2" style={{ borderBottom: "1px solid var(--border)" }}>
              <input placeholder="Filter by ticker" value={boardTicker}
                onChange={(e) => setBoardTicker(e.target.value.toUpperCase())}
                className="text-xs px-2 py-1.5 rounded w-full"
                style={{ background: "var(--panel)", border: "1px solid var(--border)", color: "var(--ink)" }} />
            </div>
            <div className="overflow-y-auto flex flex-col gap-2 p-2" style={{ maxHeight: 320 }}>
              {boardRows.filter((r) => !boardTicker || r.ticker.includes(boardTicker)).length === 0 ? (
                <p className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>
                  No tickers active yet today.
                </p>
              ) : (
                boardRows
                  .filter((r) => !boardTicker || r.ticker.includes(boardTicker))
                  .map((r) => {
                    const statusColor =
                      r.status === "trading"  ? "var(--positive)" :
                      r.status === "watching" ? "var(--accent)"   : "var(--warning, #ea941d)";
                    const statusLabel =
                      r.status === "trading" ? "Trading" : r.status === "watching" ? "Watching" : "Blocked";
                    const chips = r.status === "blocked" ? buildGateChips("blocked", r.reason_code ?? null) : null;
                    // "direction" means different things per status: "call"/"put"
                    // on trading rows (from option_type), "bullish"/"bearish" on
                    // watching rows (from INST_ORB) — normalize both to a C/P suffix.
                    const isCall = r.direction === "call" || r.direction === "bullish";
                    const isPut  = r.direction === "put"  || r.direction === "bearish";
                    const optLabel = r.contract?.strike
                      ? `${r.ticker} ${r.contract.strike}${isCall ? "C" : isPut ? "P" : ""}`
                      : r.ticker;

                    return (
                      <div key={r.ticker} className="card px-3 py-2.5" style={{ background: "var(--panel)" }}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                              {r.status === "trading" || r.status === "watching" ? optLabel : r.ticker}
                            </span>
                            {r.strategy && <span className="badge badge-blue">{r.strategy}</span>}
                          </div>
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase"
                                style={{ background: `${statusColor}22`, color: statusColor }}>
                            {statusLabel}
                          </span>
                        </div>

                        {/* Trading — real position: contract, entry→now, live P&L */}
                        {r.status === "trading" && (
                          <div className="grid grid-cols-3 gap-2 text-xs">
                            <div>
                              <div style={{ color: "var(--ink-faint)" }}>Expiration</div>
                              <div className="font-medium" style={{ color: "var(--ink)" }}>{r.contract?.expiry ?? "—"}</div>
                            </div>
                            <div>
                              <div style={{ color: "var(--ink-faint)" }}>Entry → now</div>
                              <div className="num font-medium" style={{ color: "var(--ink)" }}>
                                ${r.entry_price?.toFixed(2)} → {r.current_price != null ? `$${r.current_price.toFixed(2)}` : "—"}
                              </div>
                            </div>
                            <div>
                              <div style={{ color: "var(--ink-faint)" }}>Live P&amp;L</div>
                              <div className="num font-medium" style={{ color: r.pnl != null && r.pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                                {r.pnl != null ? `${r.pnl >= 0 ? "+" : ""}$${r.pnl.toFixed(2)}` : "—"}
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Watching — same detail the old Watching tab showed: retest
                            level, phase, expiration, current price, and a live
                            "enter if premium is X-Y" band once it's actually retesting */}
                        {r.status === "watching" && (
                          <>
                            <div className="grid grid-cols-4 gap-2 text-xs">
                              <div>
                                <div style={{ color: "var(--ink-faint)" }}>Retest level</div>
                                <div className="num font-medium" style={{ color: "var(--ink)" }}>
                                  {r.retest_level != null ? `$${r.retest_level.toFixed(2)}` : "—"}
                                </div>
                              </div>
                              <div>
                                <div style={{ color: "var(--ink-faint)" }}>Phase</div>
                                <div className="font-medium" style={{ color: "var(--ink)" }}>{r.detail.split(" — ")[0]}</div>
                              </div>
                              <div>
                                <div style={{ color: "var(--ink-faint)" }}>Expiration</div>
                                <div className="font-medium" style={{ color: "var(--ink)" }}>{r.contract?.expiry ?? "—"}</div>
                              </div>
                              <div>
                                <div style={{ color: "var(--ink-faint)" }}>Now</div>
                                <div className="num font-medium" style={{ color: "var(--ink)" }}>
                                  {r.current_price != null ? `$${r.current_price.toFixed(2)}` : "—"}
                                </div>
                              </div>
                            </div>
                            {r.contract?.bid != null && r.contract?.ask != null && (
                              <div className="mt-2 px-2 py-1 flex items-center justify-between text-xs"
                                   style={{ background: "var(--muted)", borderRadius: 6 }}>
                                <span style={{ color: "var(--ink-muted)" }}>Enter if premium is</span>
                                <span className="num font-medium" style={{ color: "var(--ink)" }}>
                                  ${r.contract.bid.toFixed(2)} – ${r.contract.ask.toFixed(2)}
                                </span>
                              </div>
                            )}
                            {r.detail.startsWith("expired") && (
                              <p className="text-xs mt-1" style={{ color: "var(--ink-faint)" }}>{r.detail}</p>
                            )}
                          </>
                        )}

                        {/* Blocked — same gate chips the Log tab used to show inline
                            in its journal rows; this is now the one place they live */}
                        {chips && (
                          <>
                            <p className="text-xs mb-1.5" style={{ color: "var(--ink-muted)" }}>{r.detail}</p>
                            <div className="flex gap-3 flex-wrap text-xs">
                              {chips.map((c) => (
                                <span key={c.label} style={{ color: c.passed ? "var(--positive)" : "var(--negative)" }}>
                                  {c.passed ? "✓" : "✗"} {c.label}
                                </span>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })
              )}
            </div>
          </div>
        )}

        {mainPanelTab === "log" && (
        <div className="card flex flex-col">
          {(() => {
            const displayLogs = logPaused ? logSnapshotRef.current : logs;
            const networkLogs  = displayLogs.filter((e) => isNetworkLog(e));
            // Signal outcome lines (SIGNAL_ENTERED/SIGNAL_BLOCKED) are shown in the
            // structured journal section above instead — filtered out here so they
            // don't appear twice in the same tab.
            const thinkingLogs = displayLogs.filter((e) =>
              !isNetworkLog(e) && e.event !== "SIGNAL_ENTERED" && e.event !== "SIGNAL_BLOCKED"
            );
            const netHasError  = networkLogs.some((e) => (e.level ?? "").toUpperCase() === "ERROR");
            const activeLogs   = logTab === "network" ? networkLogs : thinkingLogs;
            return (
              <>
                <div className="border-b flex items-center justify-between"
                     style={{ borderColor: "var(--border)" }}>
                  <div className="flex">
                    {(["thinking", "network"] as const).map((tab) => {
                      const isNetwork = tab === "network";
                      const isActive  = logTab === tab;
                      const hasNetErr = isNetwork && netHasError;
                      return (
                        <button key={tab} onClick={() => setLogTab(tab)}
                          className="px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors"
                          style={{
                            borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                            color: hasNetErr ? "var(--negative)" : isActive ? "var(--ink)" : "var(--ink-muted)",
                            background: "none", cursor: "pointer",
                          }}>
                          {tab === "thinking" ? "Thinking" : "Network"}
                          {isNetwork && netHasError && (
                            <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse align-middle" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {logPaused && (
                    <span className="badge badge-blue text-[9px] animate-pulse mr-2">⏸ PAUSED</span>
                  )}
                </div>

                {/* Ticker filter — the structured summary/chips/journal rows
                    that used to live here now live on the Board tab instead;
                    this is purely the raw scrolling narrative, filterable and
                    with repeated "no setup" filler collapsed so it's actually
                    readable instead of a wall of near-identical lines. */}
                <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
                  <input placeholder="Filter by ticker" value={logRawTicker}
                    onChange={(e) => setLogRawTicker(e.target.value.toUpperCase())}
                    className="text-xs px-2 py-1.5 rounded w-full"
                    style={{ background: "var(--panel)", border: "1px solid var(--border)", color: "var(--ink)" }} />
                </div>

                <div
                  className="flex-1 overflow-y-auto p-2 flex flex-col gap-1 font-mono text-xs"
                  style={{ maxHeight: 280, cursor: logPaused ? "text" : "default" }}
                  onMouseEnter={() => { logSnapshotRef.current = [...logs]; setLogPaused(true); }}
                  onMouseLeave={() => setLogPaused(false)}
                >
                  {(() => {
                    // Filter by ticker (checks the entry's own ticker field
                    // first, falls back to a "[TICKER]" match in the message
                    // since not every log line carries a structured field).
                    const tickerFiltered = !logRawTicker ? activeLogs : activeLogs.filter((e) => {
                      const t = typeof e.ticker === "string" ? e.ticker.toUpperCase() : "";
                      const msg = String(e.message ?? "").toUpperCase();
                      return t.includes(logRawTicker) || msg.includes(`[${logRawTicker}`);
                    });
                    // Collapse consecutive identical (ticker, message) lines —
                    // "No trade setup found" repeating every candle for the
                    // same ticker was the single biggest source of noise.
                    const collapsed: { entry: typeof tickerFiltered[number]; count: number }[] = [];
                    for (const entry of tickerFiltered) {
                      const prev = collapsed[collapsed.length - 1];
                      const sameAsPrev = prev
                        && !isSeparator(entry) && !isSeparator(prev.entry)
                        && prev.entry.ticker === entry.ticker
                        && prev.entry.message === entry.message
                        && prev.entry.event === entry.event;
                      if (sameAsPrev) { prev.count += 1; } else { collapsed.push({ entry, count: 1 }); }
                    }
                    return collapsed.slice(0, 80);
                  })().map(({ entry, count }, i) => {
                    if (isSeparator(entry)) {
                      return (
                        <div key={i} className="flex items-center gap-2 my-1 select-none"
                          style={{ color: "var(--ink-faint)", fontSize: 10 }}>
                          <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
                          <span>previous session</span>
                          <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
                        </div>
                      );
                    }
                    // 2026-07-28: "bar_conditions" lines carry a structured
                    // [{name, passed}] list (see trading/diagnostics.py) — render
                    // as simple red/green condition labels instead of parsing
                    // emoji out of a text blob. Per user request: "simpler...
                    // just red for not met, green for met, side by side."
                    if (entry.event === "bar_conditions" && Array.isArray(entry.conditions)) {
                      const conditions = entry.conditions as { name: string; passed: boolean }[];
                      return (
                        <div key={i} className="flex items-center gap-3 flex-wrap">
                          {entry.ts && (
                            <span className="opacity-60 select-none"
                              style={{ color: "var(--ink-muted)", minWidth: "6.5em", display: "inline-block" }}>
                              {entry.ts}
                            </span>
                          )}
                          {typeof entry.ticker === "string" && (
                            <span style={{ color: "var(--ink)" }}>{entry.ticker}</span>
                          )}
                          {conditions.map((c) => (
                            <span key={c.name} style={{ color: c.passed ? "var(--positive)" : "var(--negative)" }}>
                              {c.passed ? "✓" : "✗"} {c.name}
                            </span>
                          ))}
                        </div>
                      );
                    }
                    const lvl = (entry.level ?? "INFO").toUpperCase();
                    const color =
                      lvl === "ERROR"   ? "var(--negative)" :
                      lvl === "WARNING" ? "var(--warning)"  :
                      entry.event?.includes("Trade_Signal") ? "var(--positive)" :
                      "var(--ink-muted)";
                    return (
                      <div key={i} style={{ color }}>
                        {entry.ts && (
                          <span className="opacity-60 mr-1 select-none"
                            style={{ color: "var(--ink-muted)", minWidth: "6.5em", display: "inline-block" }}>
                            {entry.ts}
                          </span>
                        )}
                        {entry.event && <span className="badge badge-blue mr-1">{entry.event}</span>}
                        {String(entry.message ?? "")}
                        {count > 1 && (
                          <span className="ml-1" style={{ color: "var(--ink-faint)" }}>×{count}</span>
                        )}
                      </div>
                    );
                  })}
                  {activeLogs.length === 0 && (
                    <p style={{ color: "var(--ink-muted)" }}>
                      {logs.length === 0
                        ? "Waiting for bot…"
                        : logTab === "thinking"
                          ? "No bot activity yet — API/network events are in the Network tab"
                          : "No network events yet"}
                    </p>
                  )}
                </div>
              </>
            );
          })()}
        </div>
        )}
      </div>

      {/* ── News feed ───────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="px-3 py-2 border-b flex items-center gap-2"
             style={{ borderColor: "var(--border)" }}>
          <span className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--ink-muted)" }}>
            Market News
          </span>
          <span className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
            {newsSymbols} · via Alpaca
          </span>
        </div>
        <div className="flex flex-col divide-y" style={{ borderColor: "var(--border)" }}>
          {newsArticles.length === 0 ? (
            <p className="px-3 py-3 text-xs" style={{ color: "var(--ink-muted)" }}>
              No news available — Alpaca API key required, or no recent articles for {ticker}.
            </p>
          ) : (
            newsArticles.map((article, i) => {
              // Format timestamp as "Jul 12, 9:34 AM"
              const ts = article.created_at
                ? new Date(article.created_at).toLocaleString("en-US", {
                    month: "short", day: "numeric",
                    hour: "numeric", minute: "2-digit",
                  })
                : "";
              return (
                <div key={article.id ?? i} className="px-3 py-2">
                  <div className="flex items-start gap-2">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      {article.url ? (
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium hover:underline"
                          style={{ color: "var(--ink)", lineHeight: 1.4, display: "block" }}
                        >
                          {article.headline}
                        </a>
                      ) : (
                        <span className="text-sm font-medium" style={{ color: "var(--ink)", lineHeight: 1.4, display: "block" }}>
                          {article.headline}
                        </span>
                      )}
                      <div className="flex items-center gap-2 mt-0.5">
                        {article.source && (
                          <span className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                            {article.source}
                          </span>
                        )}
                        {ts && (
                          <span className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                            {ts}
                          </span>
                        )}
                        {article.symbols?.length > 0 && (
                          <div className="flex gap-1">
                            {article.symbols.slice(0, 4).map((s) => (
                              <span key={s} className="badge badge-blue" style={{ fontSize: 9, padding: "1px 4px" }}>
                                {s}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>

    {/* ── Trade log drawer ──────────────────────────────────────────────────── */}
    {tradeDrawerId !== null && (() => {
      const trade = openTrades.find((t: Trade) => t.id === tradeDrawerId);

      // ── Strategy education map ─────────────────────────────────────────────
      // Each entry explains: full name, setup the bot identified, what to watch,
      // and how the bot will manage the trade — so users learn while the trade runs.
      const STRAT_EDU: Record<string, { name: string; setup: string; watch: string; manage: string; color: string }> = {
        INST_ORB: {
          name: "Institutional Opening Range Breakout",
          color: "#00c853",
          setup: "The market established a clear Opening Range (OR) in the first 15–30 minutes. Price then broke above (for calls) or below (for puts) that range with volume confirmation. This is where institutional order flow often commits to a direction for the day.",
          watch: "Watch the OR High/Low lines on the chart (green = OR High, red = OR Low). If price re-enters the OR, momentum is fading. A failed breakout means the bot will stop out to protect capital.",
          manage: "The bot targets 2× risk on Stage 1, then moves stop to breakeven and lets the rest run toward 4× risk. A trailing stop activates if price extends beyond the first target.",
        },
        FVG: {
          name: "Fair Value Gap",
          color: "#f59e0b",
          setup: "An imbalance was identified on the chart — a 3-candle pattern where price moved so fast it left a price gap (Fair Value Gap). These gaps act as magnets: price often fills back into them before resuming the trend.",
          watch: "Watch for price to fill the gap and bounce. If price blows through the gap without slowing, the setup is invalidated. The bot will exit if this happens.",
          manage: "Entry is at the mid-point of the gap. Stop is below the gap's bottom edge. The bot targets the prior swing high/low as the first exit point.",
        },
        IFVG: {
          name: "Inverted Fair Value Gap",
          color: "#e879f9",
          setup: "A Fair Value Gap formed but price mitigated (filled) it and is now using the old gap as a launchpad in the opposite direction. This is a more aggressive setup indicating a potential reversal or strong continuation after the initial fill.",
          watch: "The key level is the old FVG zone — now acting as support (for calls) or resistance (for puts). If price closes back inside the inverted gap, the setup fails.",
          manage: "Smaller position size due to the reversal nature. Stop sits just beyond the IFVG extreme. Bot exits Stage 1 quickly to lock in premium.",
        },
        VWAP_PB: {
          name: "VWAP Pullback",
          color: "#2962ff",
          setup: "Price was trending strongly away from VWAP (the blue line on the chart), then pulled back to touch or test it. The bot entered as price bounced off VWAP with a confirmed candle showing rejection.",
          watch: "The blue VWAP line is your key level — it acts like a live moving average of fair value for the day. As long as price holds above VWAP (for calls) or below (for puts), the trend is intact. A VWAP recross in the wrong direction is the exit signal.",
          manage: "VWAP trades tend to be shorter in duration. The bot sets a tight stop below the pullback candle and targets the morning high/low for first exit.",
        },
        MID_BRK: {
          name: "Mid-Day Breakout",
          color: "#06b6d4",
          setup: "After the initial morning volatility settled into a consolidation range (roughly 10:30–12:00 ET), price broke out of that tight range. Mid-day breakouts are less crowded trades that can produce clean trends into the afternoon.",
          watch: "The breakout level is your anchor. A retest of the breakout point that holds = healthy. A close back inside the range = the bot exits. Volume should confirm — low-volume breakouts are more likely to fail.",
          manage: "The bot uses a wider initial stop on mid-day setups because midday ranges are smaller. First target is the morning's high or low.",
        },
        AFT_REV: {
          name: "Afternoon Reversal",
          color: "#f97316",
          setup: "Price made an extended move in one direction throughout the day, then showed signs of exhaustion and reversal in the 2–3 PM ET window. This captures the afternoon mean-reversion move as intraday traders unwind positions before the close.",
          watch: "Afternoon reversals can be sharp but also whippy. The bot holds a smaller position than usual. Watch for the 3:30 PM ET window — if the move hasn't materialized, the bot will close to avoid holding into the close.",
          manage: "Hard stop at 3:50 PM ET regardless of price — no holding options into the close. First target is a 50% retrace of the day's trend move.",
        },
        TREND_CONT: {
          name: "Trend Continuation",
          color: "#84cc16",
          setup: "The bot identified a clear intraday trend (series of higher highs / higher lows for calls, or lower highs / lower lows for puts), and entered on a brief consolidation or flag pattern within that trend.",
          watch: "Trend continuation trades require the trend to stay intact. Each new candle should respect the trend structure. A lower low (for calls) or higher high (for puts) signals the trend may be breaking down and the bot will exit.",
          manage: "This is the highest-conviction setup in the playbook. Bot uses full position size and a trailing stop that tightens as the trade progresses. Hold time can be longer than other strategies.",
        },
        BOS_MSS: {
          name: "Break of Structure / Market Structure Shift",
          color: "#a78bfa",
          setup: "Price broke a key swing high (bullish BOS) or swing low (bearish BOS), signaling a change in the dominant order flow direction. A Market Structure Shift (MSS) is a BOS against the prevailing trend — indicating a potential trend reversal.",
          watch: "The broken swing level is now the key reference. For calls, a re-break below the BOS level invalidates the setup. Watch for price to confirm the new direction with follow-through, not just a wick.",
          manage: "BOS trades enter on the retest of the broken level. Stop goes just beyond the swing that was broken. Target is the next major swing point in the direction of the break.",
        },
        CHAN_BREAK: {
          name: "Channel Breakout",
          color: "#fb923c",
          setup: "Price was channeling (moving in a parallel range with defined highs and lows) before breaking decisively out of one side of the channel. Channel breakouts often produce some of the strongest directional moves of the day.",
          watch: "The channel boundary (the level that was broken) now acts as support (for upside breaks) or resistance (for downside breaks). If price falls back into the channel, the bot exits — the breakout failed.",
          manage: "Entry is just beyond the channel boundary on a confirmed close. Target is the channel width projected from the break point. Bot trails stop along the channel boundary once the trade is in profit.",
        },
      };

      const edu = trade?.strategy_id ? (STRAT_EDU[trade.strategy_id] ?? null) : null;

      const levelColor = (lvl: string) => {
        if (lvl === "ERROR" || lvl === "CRITICAL") return "#f87171";
        if (lvl === "WARNING") return "#fbbf24";
        return "var(--ink-muted)";
      };
      return (
        <div style={{
          position: "fixed", top: 0, right: 0, bottom: 0, width: 420,
          background: "var(--surface)", borderLeft: "1px solid var(--border)",
          boxShadow: "-4px 0 24px rgba(0,0,0,0.18)", zIndex: 200,
          display: "flex", flexDirection: "column",
        }}>
          {/* Header */}
          <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span className="font-semibold" style={{ color: "var(--ink)", fontSize: 14 }}>
                {trade?.ticker ?? "Trade"} — Bot Thinking Log
              </span>
              {trade && (
                <span className="text-xs ml-2" style={{ color: "var(--ink-muted)" }}>
                  {trade.direction?.toUpperCase()} · {trade.strategy_id} · Entry ${trade.entry_price?.toFixed(2)}
                </span>
              )}
            </div>
            <button onClick={() => setTradeDrawerId(null)}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "var(--ink-muted)", lineHeight: 1 }}>
              ✕
            </button>
          </div>

          {/* ── Strategy education card ── */}
          {edu && (
            <div style={{
              margin: "10px 12px 0", borderRadius: 10, overflow: "hidden",
              border: `1px solid ${edu.color}33`,
            }}>
              {/* Card header */}
              <div style={{ background: `${edu.color}18`, padding: "8px 12px", display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: edu.color, flexShrink: 0 }} />
                <span style={{ fontSize: 11, fontWeight: 700, color: edu.color }}>{edu.name}</span>
              </div>
              {/* Card body */}
              <div style={{ padding: "10px 12px", background: "var(--surface-raised)", display: "flex", flexDirection: "column", gap: 8 }}>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>
                    📡 Setup the bot saw
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: "var(--ink)", lineHeight: 1.55 }}>{edu.setup}</p>
                </div>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>
                    👁 What to watch
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: "var(--ink)", lineHeight: 1.55 }}>{edu.watch}</p>
                </div>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--ink-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3 }}>
                    🤖 How the bot manages it
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: "var(--ink)", lineHeight: 1.55 }}>{edu.manage}</p>
                </div>
              </div>
            </div>
          )}

          {/* Log entries */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 12px", fontSize: 11, fontFamily: "monospace", marginTop: edu ? 8 : 0 }}>
            {tradeEvents.length === 0 ? (
              <p style={{ color: "var(--ink-muted)", marginTop: 16, textAlign: "center" }}>
                No bot log entries yet for this trade.<br/>
                <span style={{ fontSize: 10 }}>Events appear as the bot evaluates this ticker.</span>
              </p>
            ) : (
              [...tradeEvents].reverse().map((ev, i) => {
                const ts = ev.ts?.slice(11, 19) ?? "";   // HH:MM:SS from ISO
                return (
                  <div key={i} style={{ marginBottom: 6, paddingBottom: 6, borderBottom: "1px solid var(--border-faint, var(--border))" }}>
                    <span style={{ color: "var(--ink-faint, var(--ink-muted))", marginRight: 6 }}>{ts}</span>
                    <span style={{ color: levelColor(ev.level), marginRight: 6, fontWeight: 600 }}>{ev.level !== "INFO" ? ev.level : ""}</span>
                    <span style={{ color: "var(--ink)", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{ev.message}</span>
                  </div>
                );
              })
            )}
          </div>

          <div style={{ padding: "8px 16px", borderTop: "1px solid var(--border)", fontSize: 10, color: "var(--ink-muted)" }}>
            {tradeEvents.length} events · auto-refreshes every 5s · newest first
          </div>
        </div>
      );
    })()}
    </>
  );
}
