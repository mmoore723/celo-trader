/**
 * LiveTrading.tsx — Main trading cockpit.
 * Real-time chart, actionable trade alert, open positions, eval log, scanner.
 */
import { useEffect, useState, useMemo, useRef, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChevronDown, Newspaper, RefreshCw, Radio, Bot } from "lucide-react";
import { BoomerangReplay, type BoomerangReplayHandle } from "../components/charts/BoomerangReplay";
import { useBotStore } from "../store/bot";
import { api, type Trade, type ChartAnnotation, type NewsArticle, type ScannerOpportunity } from "../lib/api";
import { setupDrawings } from "../lib/setupDrawings";
import { stockPositionDrawings } from "../lib/stockPositionDrawings";
import { dedupeLatestEpisodes, lifecycleCopy, opportunityLifecycle } from "../lib/opportunitySemantics.js";
import { openingRangeForBars } from "../lib/chartSession.js";
import { newYorkDateKey } from "../lib/marketSession.js";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { OptionPositionChart } from "../components/charts/OptionPositionChart";
import { useOptionChartSelection } from "../components/charts/useOptionChartSelection";
import { connectionHealthView } from "../lib/connectionHealthView.js";

const FALLBACK_TICKERS = ["SPY", "QQQ"];

type Period = "1D" | "5D" | "1M" | "3M";

// PERIOD_MS was used by KChart for windowing; TradingChart handles it internally

function barLimitForPeriod(tf: string, period: Period): number {
  const barsPerDay: Record<string, number> = {
    // Regular US session is 390 minutes.  These counts intentionally exclude
    // extended hours because the chart and bot both use 09:30–16:00 ET.
    "1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7,
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
  const [tf,              setTf]              = useState("1Min");
  const [period,          setPeriod]          = useState<Period>("1D");
  const [showVwap,        setShowVwap]        = useState(true);
  const [showOR,          setShowOR]          = useState(true);
  const [showSwings,      setShowSwings]      = useState(false);
  const [selectedSetup, setSelectedSetup] = useState<ScannerOpportunity | undefined>();
  const [drawingEnabled,  setDrawingEnabled]  = useState(false);
  const [clearDrawingsToken, setClearDrawingsToken] = useState(0);
  // Board is the current per-ticker view (trading/watching/blocked).
  const [mainPanelTab,    setMainPanelTab]    = useState<"board" | "log">("board");
  const [boardTicker,     setBoardTicker]     = useState("");
  const [logPaused,       setLogPaused]       = useState(false);
  const logSnapshotRef  = useRef<typeof logs>([]);
  const [logTab,         setLogTab]           = useState<"thinking" | "network">("thinking");
  const [logRawTicker,   setLogRawTicker]     = useState("");
  const [tradeDrawerId,  setTradeDrawerId]    = useState<number | null>(null);
  const [newsExpanded,   setNewsExpanded]     = useState(false);
  const [chartExpanded,  setChartExpanded]    = useState(() => {
    try {
      const saved = window.localStorage.getItem("celo-live-chart-expanded");
      return saved == null ? true : saved === "true";
    } catch {
      return true;
    }
  });
  const chartReplayRef  = useRef<BoomerangReplayHandle>(null);
  // Once opened, keep the stock chart mounted while the option view is shown.
  // Recreating lightweight-charts on every switch can leave a queued resize
  // callback touching an already-disposed canvas.
  const stockChartWasOpened = useRef(false);
  const lastFramedPosition = useRef("");

  function toggleChart() {
    setChartExpanded((expanded) => {
      const next = !expanded;
      try { window.localStorage.setItem("celo-live-chart-expanded", String(next)); } catch { /* optional preference */ }
      return next;
    });
  }

  const { status, logs } = useBotStore();
  const tradeMode = status?.mode === "live" ? "live" : "paper";
  const {
    data: connectionHealth,
    isFetching: checkingConnections,
    isError: connectionCheckFailed,
    refetch: refreshConnections,
  } = useQuery({
    queryKey: ["broker-connection-health"],
    queryFn: api.settings.connectionHealth,
    enabled: mainPanelTab === "log" && logTab === "network",
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
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

  // Mid-session, even a one-day-sized tail can include yesterday because the
  // current session is not complete yet.  A 1D chart must display one actual
  // trading date, not "the last N bars" spanning two dates.  Keep longer
  // period views unchanged.
  const chartBars = useMemo(() => {
    if (effectivePeriod !== "1D" || bars.length === 0) return bars;
    const latestDay = bars.reduce((latest, bar) => {
      const day = String(bar.time ?? "").slice(0, 10);
      return day > latest ? day : latest;
    }, "");
    return bars.filter((bar) => String(bar.time ?? "").slice(0, 10) === latestDay);
  }, [bars, effectivePeriod]);

  const { data: openTrades = [] } = useQuery({
    queryKey: ["open-trades", tradeMode],
    queryFn: api.trades.open,
    refetchInterval: 5_000,
  });

  const { data: todayTradesRaw = [] } = useQuery({
    queryKey: ["today-trades", tradeMode],
    queryFn: () => api.trades.list(tradeMode, "all"),
    refetchInterval: 10_000,
    select: (res: any) => {
      const today = newYorkDateKey();
      return (res?.trades ?? []).filter((t: Trade) =>
        t.entry_time != null && (/Z$|[+-]\d{2}:\d{2}$/.test(t.entry_time)
          ? newYorkDateKey(t.entry_time) : t.entry_time.slice(0, 10)) === today
      );
    },
  });

  const { data: scanner = [] } = useQuery({
    queryKey: ["scanner"],
    queryFn: api.market.scanner,
    refetchInterval: 60_000,
  });

  // This is deliberately the same durable scanner-candidate trail shown on
  // Scanner Opportunities.  The old websocket eval log is still useful for
  // the one-line live trade alert above, but it is not a reliable history:
  // it disappears on refresh and never contained the full contract/exit plan.
  const { data: scannerOpportunityData } = useQuery({
    queryKey: ["scanner-opportunities-preview"],
    queryFn: () => api.signals.opportunities({ feed: "operational", limit: 4 }),
    refetchInterval: 15_000,
    retry: false,
  });
  // The live sidebar is a glanceable alert feed, not the full audit trail.
  // Collapse repeated observations of the same setup and keep the newest one.
  const scannerOpportunityPreview = useMemo(() => {
    return dedupeLatestEpisodes(scannerOpportunityData?.entries ?? [], 3);
  }, [scannerOpportunityData]);

  const { data: or } = useQuery({
    queryKey: ["or", ticker],
    queryFn: () => api.market.or(ticker),
    enabled: showOR,
    refetchInterval: 300_000,
  });


  // "Board" — one row per ticker, current state only (trading/watching/
  // blocked). See api/routes/tickers.py::get_board() — merges open
  // positions and today's signal journal so this
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
  const optionChart = useOptionChartSelection(
    ticker, [...openTrades, ...tickerTrades], setTicker, setChartExpanded, "stock",
    () => {
      stockChartWasOpened.current = true;
      setTf("1Min");
      setPeriod("1D");
    },
  );
  const openTickerTrade   = tickerTrades.find((t: Trade) => !t.exit_time);
  const displayedTrade    = optionChart.selected ?? openTickerTrade;
  const { data: selectedTradeSetups } = useQuery({
    queryKey: ["stock-position-setup", displayedTrade?.mode, displayedTrade?.id, ticker],
    queryFn: () => api.signals.opportunities({ feed: "operational", ticker,
      date: displayedTrade?.entry_time?.slice(0, 10), outcome: "entered", limit: 100 }),
    enabled: chartExpanded && optionChart.view === "stock" && !!displayedTrade,
    staleTime: 60_000, retry: false,
  });
  const matchedTradeSetup = (selectedTradeSetups?.entries ?? scannerOpportunityData?.entries ?? [])
    .find(row => row.ticker === ticker && row.trade?.id === displayedTrade?.id);
  const chartSetup = selectedSetup?.ticker === ticker
    ? (scannerOpportunityPreview.find(row => row.id === selectedSetup.id) ?? selectedSetup)
    : matchedTradeSetup
      ?? scannerOpportunityPreview.find(row => row.ticker === ticker);
  const setupLevels = setupDrawings(chartSetup);
  const setupTrade = chartSetup?.trade?.id != null
    ? tickerTrades.find(row => row.id === chartSetup.trade!.id) : undefined;
  const stockPositionLevels = stockPositionDrawings(displayedTrade, matchedTradeSetup);
  const chartAnnotations = [...(chartSetup
    ? [...(setupTrade?.annotations ?? []), ...setupLevels]
    : [...annotations, ...(displayedTrade?.annotations ?? [])]), ...stockPositionLevels];

  // A selected position is a focused teaching view: show exactly 20 complete
  // one-minute stock candles before its buy minute through 20 after its close.
  useEffect(() => {
    const selected = optionChart.selected;
    if (optionChart.view !== "stock" || tf !== "1Min" || !selected?.entry_time || chartBars.length === 0 || !chartReplayRef.current) return;
    const entry = Date.parse(selected.entry_time);
    if (entry < Date.parse(chartBars[0].time) || entry > Date.parse(chartBars.at(-1)!.time) + 60_000) return;
    const key = `${selected.mode}:${selected.id}:${selected.entry_time}:${selected.exit_time ?? "open"}`;
    if (lastFramedPosition.current === key) return;
    lastFramedPosition.current = key;
    chartReplayRef.current?.showTradeWindow(selected.entry_time, selected.exit_time);
  }, [optionChart.selected, optionChart.view, tf, chartBars]);

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

  // An opening range is valid only for the same trading session as the bars
  // on screen. The old 15%-from-last-price check accepted yesterday's range,
  // which is exactly how a $775 OR flattened today's $763 candles into a
  // narrow band with a large blank area above them.
  const visibleOpeningRange = openingRangeForBars(chartBars, or, showOR);
  const safeOrHigh = visibleOpeningRange.high;
  const safeOrLow = visibleOpeningRange.low;

  // FIX 2026-07-17: "no_signal" (no setup found at all) used to render as a
  // compact-but-still-visible "SKIP · no setup" row. That's the single most
  // common evaluation outcome (most bars have no setup), so it drowned out
  // the genuinely informative skip reasons (low confidence, spread too wide,
  // R:R too low, etc.) — dropped entirely per explicit ask instead of just
  // compacted.
  const evalLog: any[] = ((status as any)?.eval_log ?? [])
    .filter((ev: any) => !(ev.rejected && ev.reason === "no_signal"));
  // A rejected evaluation is useful in Board/Scanner Opportunities, but it is
  // not a trade alert. Only surface an evaluation here once contract pricing
  // and an executable entry plan exist. This also keeps the live page compact
  // while the scanner is merely idle.
  const latestSignal = evalLog.find((ev: any) =>
    !ev.rejected
    && ["call", "put"].includes(String(ev.opt_type ?? "").toLowerCase())
    && Number(ev.eff_entry) > 0
    && Number(ev.contracts) > 0
  ) ?? null;
  return (
    <>
    <div className="p-4 flex flex-col gap-4">

      {/* One account ribbon establishes context without seven competing cards. */}
      <section className="card px-4 py-3 flex flex-col gap-3 lg:flex-row lg:items-center" aria-label="Trading account snapshot">
        <div className="flex items-center gap-2 lg:pr-5 lg:border-r" style={{ borderColor: "var(--border)" }}>
          <span className="text-sm font-semibold">Trading workspace</span>
          <span className={`badge ${status?.is_paper !== false ? "badge-yellow" : "badge-green"}`}>
            {status?.is_paper !== false ? "Paper" : "Live"}
          </span>
          <span className="text-xs" style={{ color: status?.running ? "var(--positive)" : "var(--ink-muted)" }}>
            {status?.running ? "Bot running" : "Bot stopped"}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-5 lg:flex-1">
          {[
            { label: "Equity", value: status?.broker_connected ? `$${status.account_balance.toFixed(2)}` : "Not connected" },
            { label: "Day open", value: status?.broker_connected ? `$${(status.day_start_balance ?? status.account_balance).toFixed(2)}` : "—" },
            { label: "Today", value: <PnlBadge value={status?.session_pnl} /> },
            { label: "Buying power", value: `$${(status?.options_buying_power ?? 0).toFixed(2)}` },
            { label: "Open positions", value: openTrades.length },
          ].map(item => <div key={item.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wide text-ink-muted">{item.label}</dt>
            <dd className="num text-sm font-semibold truncate">{item.value}</dd>
          </div>)}
        </dl>
      </section>

      {status?.opportunity_window?.expires_at && (
        <div
          className="card px-4 py-3 flex flex-col gap-1"
          style={{ borderLeft: "4px solid #8b5cf6", background: "rgba(139, 92, 246, 0.06)" }}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="font-semibold text-sm" style={{ color: "#7c3aed" }}>Research window — no order yet</span>
            <span className="text-xs font-mono" style={{ color: "var(--ink-muted)" }}>
              ends {new Date(status.opportunity_window.expires_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
            </span>
          </div>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
            Comparing lower-confidence setups. Current best: {status.opportunity_window.ticker ?? "—"} · {status.opportunity_window.strategy_id ?? "—"} · {((status.opportunity_window.confidence ?? 0) * 100).toFixed(0)}%. It must still confirm when the 15-minute window ends.
          </p>
        </div>
      )}

      {/* Only occupy this space when the bot has a fully priced trade plan. */}
      {latestSignal && <div
        className="card px-4 py-3"
        style={{
          borderLeft: `4px solid ${latestSignal.mode === "signal" ? "var(--warning)" : "var(--positive)"}`,
        }}
      >
        {/* Header row */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {latestSignal.mode === "signal"
              ? <Radio size={14} style={{ color: "var(--warning)" }} />
              : <Bot size={14} style={{ color: "var(--positive)" }} />
            }
            <span className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--ink-muted)" }}>
              Latest Trade Alert
            </span>
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
          </div>
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
        </div>

        {/* Signal content */}
        {(() => {
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
      </div>}

      {/* Chart left, supporting activity right; stacked on smaller screens. */}
      <div className="live-trading-workspace">
        {/* Chart panel */}
        <div className="card overflow-hidden min-w-0" data-testid="live-chart-panel">
          <div
            className="flex items-center gap-3 px-4 py-3"
            style={{ borderBottom: chartExpanded ? "1px solid var(--border)" : undefined }}
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                {ticker} {optionChart.selected ? "position" : "market"} chart
              </div>
              <div className="text-xs" style={{ color: "var(--ink-muted)" }}>
                {optionChart.view === "option"
                  ? "Exact option trades; blank minutes mean the contract did not trade."
                  : optionChart.selected
                    ? "True one-minute stock candles with the option position overlaid."
                    : "True one-minute stock candles, levels, and setup context."}
              </div>
            </div>
            <div className="flex-1" />
            <button
              type="button"
              className="btn btn-sm btn-ghost shrink-0"
              onClick={toggleChart}
              aria-expanded={chartExpanded}
              aria-controls="live-market-chart"
            >
              {chartExpanded ? "Minimize chart" : "Show chart"}
              <ChevronDown
                size={15}
                aria-hidden="true"
                style={{ transform: chartExpanded ? "rotate(180deg)" : undefined }}
              />
            </button>
          </div>
          {chartExpanded && <div id="live-market-chart">
          {optionChart.selected && <div className="flex flex-wrap items-center gap-2 p-3 border-b" style={{ borderColor: "var(--border)" }}>
            {(["stock", "option"] as const).map(view => <button key={view} type="button" aria-pressed={optionChart.view === view}
              className={`btn btn-sm ${optionChart.view === view ? "btn-primary" : "btn-ghost"}`} onClick={() => {
                if (view === "stock") {
                  stockChartWasOpened.current = true;
                  setTf("1Min");
                  setPeriod("1D");
                }
                optionChart.setView(view);
              }}>
              {view === "option" ? "Option trades" : "1-minute stock"}</button>)}
            {optionChart.available.length > 1 && <select aria-label="Chart position" className="select max-w-full"
              value={`${optionChart.selected.mode}:${optionChart.selected.id}`} onChange={e => {
                const trade = optionChart.available.find(t => `${t.mode}:${t.id}` === e.target.value);
                if (trade) optionChart.selectOption(trade);
              }}>{optionChart.available.map(t => <option key={`${t.mode}:${t.id}`} value={`${t.mode}:${t.id}`}>
                {t.strike} {t.option_type} · {t.expiry} · {t.exit_time ? "Closed" : "Open"}
              </option>)}</select>}
          </div>}
          {optionChart.selected && optionChart.view === "option" && <div>
            <OptionPositionChart key={`${optionChart.selected.mode}:${optionChart.selected.id}`} trade={optionChart.selected} />
          </div>}
          {(optionChart.view === "stock" || stockChartWasOpened.current) && <div hidden={optionChart.view !== "stock"}>
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
                ["OR",     showOR,          setShowOR],
                ["Structure", showSwings,   setShowSwings],
              ] as [string, boolean, (v: boolean) => void][]).map(([label, val, setter]) => (
                <button key={label}
                  className={`btn btn-sm ${val ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setter(!val)}>
                  {label}
                </button>
              ))}
              <button
                type="button"
                className={`btn btn-sm ${drawingEnabled ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setDrawingEnabled((enabled) => !enabled)}
                aria-pressed={drawingEnabled}
                title="Click two chart points to draw a trend line"
              >
                Draw line
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  setClearDrawingsToken((token) => token + 1);
                  setDrawingEnabled(false);
                }}
                title="Remove all manual trend lines"
              >
                Clear lines
              </button>
            </div>
            <div className="flex-1" />
            {barsLoading && <RefreshCw size={13} className="animate-spin text-ink-muted" />}
          </div>
          {/* Rebuilt 2026-07-19 on the new single chart engine (TradeChart +
              BoomerangReplay) — replaces the old KChart/ChartReplay pair.
              Native lightweight-charts pan/zoom/timeframe switching (no
              custom wheel/resize workarounds), real shaded zones, and the
              "Watch this setup" boomerang jump-to-time with narration. */}
          {chartSetup && <div className="px-3 py-2 text-xs border-t">
            <b>Recorded setup: {chartSetup.ticker} · {chartSetup.strategy_id.replace(/^V2_/, "").replaceAll("_", " ")}</b>
            <p>{chartSetup.entry_plan?.trigger || chartSetup.reason_detail || "Recorded setup evidence"}</p>
            <p>{setupLevels.length ? "Lines show the price levels saved when this setup was evaluated. Click a setup card to change drawings." : "No price levels were saved for this setup. No pattern or resistance levels have been invented."}</p>
            {setupLevels.filter(row => row.type === "hline").map(row => <span key={row.id} className="inline-block mr-3">{row.label}: ${row.price!.toFixed(2)}</span>)}
          </div>}
          {displayedTrade && <div className="px-3 py-2 text-xs text-ink-muted">
            Stock-price risk/reward references for trade #{displayedTrade.id}. Option premium paid: ${displayedTrade.entry_price.toFixed(2)} x 100 x {displayedTrade.contracts} contracts.
            {stockPositionLevels.filter(row => row.type === "zone").length < 2 ? " Some stock entry/stop/target levels were not recorded; missing boxes are not invented." : " Stock moves are not option-dollar P&L."}
          </div>}
          <BoomerangReplay
            ref={chartReplayRef}
            mode="live"
            resetKey={`${ticker}|${tf}|${effectivePeriod}`}
            bars={chartBars}
            trades={tickerTrades}
            showVwap={showVwap}
            showVwapBands={false}
            showOR={showOR}
            showSwings={showSwings}
            drawingEnabled={drawingEnabled}
            clearDrawingsToken={clearDrawingsToken}
            showPositionCard={false}
            showRsi
            showMacd
            orHigh={safeOrHigh}
            orLow={safeOrLow}
            positionLevels={undefined}
            currentOptionPrice={
              displayedTrade
                ? (displayedTrade.exit_price
                  ?? status?.open_positions?.[String(displayedTrade.id)]?.current_option_price
                  ?? null)
                : null
            }
            ticker={ticker}
            height={500}
            annotations={chartAnnotations}
            narrationEvents={narrationEvents}
          />
          </div>}
          </div>}
        </div>

        <aside className="live-trading-details" aria-label="Trading activity beside chart">
        {/* Focused pre-entry callouts. The redundant ticker scanner and raw
            option-chain widgets were removed from the trading cockpit. */}
        <div className="card flex flex-col">
          {/* Keep this as a compact live snapshot of the exact same durable,
              day-by-day scanner trail shown on Scanner Opportunities. */}
          <div className="border-t px-3 py-2 flex flex-wrap gap-2 items-center justify-between"
               style={{ borderColor: "var(--border)" }}>
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider"
                    style={{ color: "var(--ink-muted)" }}>Setups and recent trades</span>
              <p className="text-[10px] text-ink-faint">Past entries are not open positions. Click a card to see its recorded chart levels.</p>
            </div>
            <Link to="/journal?tab=decisions" className="text-[10px] font-medium" style={{ color: "var(--accent)" }}>Open Journal → Bot Decisions</Link>
          </div>
          <div className="overflow-y-auto flex-1 p-2" style={{ background: "var(--surface-raised)" }}>
            {scannerOpportunityPreview.length === 0 ? (
              <p className="text-xs px-3 pb-3" style={{ color: "var(--ink-muted)" }}>
                {status?.running
                  ? "Scanning… a setup appears here when it advances toward a trade"
                  : "Waiting for bot to start scanning…"}
              </p>
            ) : (
              <div className="grid gap-2">{scannerOpportunityPreview.map((opportunity: any) => {
                const lifecycle = opportunityLifecycle(opportunity);
                const linked = todayTradesRaw.find((row: Trade) => row.id === opportunity.trade?.id);
                const lifecycleText = lifecycleCopy(linked ? { ...opportunity, trade: linked } : opportunity);
                const isEntered = lifecycle === "entered";
                // Scanner candidates use the same "bullish" / "bearish"
                // vocabulary as the entry router.  Do not silently call a
                // bullish setup a put because a different page uses long/short.
                const isBullish = ["bullish", "long"].includes((opportunity.direction ?? "").toLowerCase());
                const contract = opportunity.contract ?? {};
                const trade = linked ?? opportunity.trade ?? {};
                const optionType = contract.option_type ?? trade.option_type ?? (isBullish ? "call" : "put");
                const strike = contract.strike ?? trade.strike;
                const expiry = contract.expiry ?? trade.expiry;
                const estimatedEntry = contract.estimated_entry_price ?? contract.ask ?? trade.entry_price;
                const observedTime = opportunity.observed_at
                  ? new Date(opportunity.observed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                  : "—";
                const decision = opportunity.reason_detail
                  ?? opportunity.reason_code
                  ?? opportunity.entry_plan?.trigger
                  ?? "Scanner setup detected";
                const quantity = opportunity.planned_quantity ?? trade.contracts;
                const strategyName = String(opportunity.strategy_id ?? "Setup").replace(/^V2_/, "").replaceAll("_", " ");
                const statusTitle = lifecycleText.title;
                const accent = isEntered
                  ? "var(--positive)"
                  : lifecycle === "stopped" ? "var(--negative)" : "var(--accent)";
                return (
                  <button key={opportunity.id}
                    className="w-full text-left mb-2 rounded-lg hover:bg-muted transition-colors"
                    style={{
                      border: "1px solid var(--border)", borderLeft: `4px solid ${accent}`,
                      background: "var(--surface)", padding: "10px 11px", boxShadow: "var(--shadow-sm)",
                    }}
                    title={`Open ${opportunity.ticker} on the chart`}
                    onClick={() => { setSelectedSetup(opportunity); setTicker(opportunity.ticker); setChartExpanded(true); optionChart.setView("stock"); setTf("1Min"); setPeriod("1D"); stockChartWasOpened.current = true; }}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div>
                        <div className="text-[11px] font-bold" style={{ color: accent }}>
                          {String(optionType).toUpperCase()} IDEA · {opportunity.ticker}
                        </div>
                        <div className="text-[10px] font-semibold" style={{ color: "var(--ink)" }}>{statusTitle}</div>
                        <div className="text-[9px] mt-0.5" style={{ color: "var(--ink-faint)" }}>{observedTime}</div>
                      </div>
                      <span style={{
                        fontSize: 8, fontWeight: 700, padding: "2px 5px", borderRadius: 3,
                        background: isEntered ? "rgba(34,197,94,0.15)" : "rgba(139,148,158,0.15)",
                        color: isEntered ? "var(--positive)" : "var(--ink-muted)",
                      }}>
                        {lifecycleText.badge}
                      </span>
                    </div>
                    <div className="text-[10px] leading-relaxed" style={{ color: "var(--ink)" }}>
                      <div><b>Symbol:</b> {opportunity.ticker} &nbsp; <b>Strategy:</b> {strategyName}</div>
                      {lifecycleText.badge === "CLOSED" && <div><b>Closed P&amp;L:</b> <PnlBadge value={trade.pnl ?? undefined} />{trade.exit_reason && <span> · Exit: {trade.exit_reason === "research_missing_bars" ? "required market candles were missing" : trade.exit_reason}</span>}</div>}
                      <div><b>Position:</b> {String(optionType).toUpperCase()}{strike != null ? ` $${Number(strike).toFixed(0)}` : ""}</div>
                      {expiry && <div><b>Expiration:</b> {fmtExp(expiry)}</div>}
                      {(quantity != null || estimatedEntry != null) && (
                        <div>
                          {quantity != null && <><b>Quantity:</b> {quantity}</>}
                          {quantity != null && estimatedEntry != null && "  ·  "}
                          {estimatedEntry != null && <><b>Entry:</b> ${Number(estimatedEntry).toFixed(2)}</>}
                        </div>
                      )}
                    </div>
                    <div className="mt-1.5 text-[9px] leading-snug" style={{ color: "var(--ink-muted)" }}>
                      <b style={{ color: "var(--ink)" }}>{lifecycle === "stopped" ? "Stopped:" : "Status:"}</b> {decision || lifecycleText.detail}
                    </div>
                  </button>
                );
              })}</div>
            )}
          </div>
        </div>
      {/* ── Manage positions, then inspect the bot's activity ─────────────── */}
      <div className="card overflow-hidden">
        {/* Open positions */}
        <div>
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
                        <td className="font-semibold" style={{ color: "var(--accent)" }}>
                          <button type="button" onClick={(e) => { e.stopPropagation(); optionChart.selectOption(t); }}
                            aria-label={`View ${t.ticker} option chart`} title={`View ${t.ticker} option chart`}>{t.ticker}</button>
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

      </div>

      <div className="card overflow-hidden flex flex-col">
        <div className="px-3 pt-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">Live activity</div>
        <div className="flex flex-col">
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
          <div className="flex flex-col">
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
                    // watching rows use bullish/bearish — normalize both to a C/P suffix.
                    const isCall = r.direction === "call" || r.direction === "bullish";
                    const isPut  = r.direction === "put"  || r.direction === "bearish";
                    const optLabel = r.contract?.strike
                      ? `${r.ticker} ${r.contract.strike}${isCall ? "C" : isPut ? "P" : ""}`
                      : r.ticker;

                    // One plain-language sentence per ticker instead of a
                    // grid of labels — say what's happening the way you'd
                    // say it out loud, with the real numbers dropped in.
                    let sentence: ReactNode = null;
                    if (r.status === "trading") {
                      const upDown = r.pnl != null && r.pnl >= 0 ? "up" : "down";
                      sentence = (
                        <>
                          In a trade on {r.ticker}: bought the{" "}
                          <strong>{optLabel}{r.contract?.expiry ? `, exp ${r.contract.expiry}` : ""}</strong>{" "}
                          at <strong>${r.entry_price?.toFixed(2)}</strong>, now worth{" "}
                          <strong>{r.current_price != null ? `$${r.current_price.toFixed(2)}` : "—"}</strong>
                          {r.pnl != null && (
                            <> — {upDown}{" "}
                              <strong style={{ color: r.pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                                ${Math.abs(r.pnl).toFixed(2)}
                              </strong>
                            </>
                          )}.
                        </>
                      );
                    } else if (r.status === "watching" && r.detail.startsWith("expired")) {
                      sentence = <>Was watching {r.ticker} — the setup expired ({r.detail.replace("expired — ", "")}).</>;
                    } else if (r.status === "watching") {
                      // FIX 2026-07-31: this used to be two DIFFERENT formats — phase 1
                      // ("1 of 3", breakout_seen) got a bare "not locked in yet" line with
                      // no contract shown, phase 2 ("2 of 3", retesting) got the full
                      // approved-mockup sentence (strike/expiry/bid-ask). The backend
                      // (resolve_watching_contracts) resolves a real contract for BOTH
                      // phases identically, so there was never a real reason for phase 1
                      // to withhold it — same detailed sentence for both now, differing
                      // only in what's being waited for (touch vs. bounce-through).
                      const isRetesting = r.detail.startsWith("2 of 3");
                      sentence = (
                        <>
                          Watching {r.ticker} for the{" "}
                          <strong>{optLabel}{r.contract?.expiry ? `, exp ${r.contract.expiry}` : ""}</strong>
                          {" "}— waiting for price to{" "}
                          {isRetesting
                            ? <>bounce back through{" "}</>
                            : <>pull back and retest{" "}</>}
                          <strong>{r.retest_level != null ? `$${r.retest_level.toFixed(2)}` : "that level"}</strong>{" "}
                          before entering.
                          {r.contract?.bid != null && r.contract?.ask != null && (
                            <> Would cost <strong>${r.contract.bid.toFixed(2)}–${r.contract.ask.toFixed(2)}</strong> right now.</>
                          )}
                        </>
                      );
                    } else {
                      sentence = (
                        <>{r.ticker} fired a {r.direction ?? "signal"} on {r.strategy ?? "a strategy"} but{" "}
                          {r.detail || "didn't clear a gate"} — skipped, nothing to watch here.</>
                      );
                    }

                    return (
                      <div key={r.ticker} className="card px-3 py-2.5" style={{ background: "var(--panel)" }}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                              {r.ticker}
                            </span>
                            {r.strategy && <span className="badge badge-blue">{r.strategy}</span>}
                          </div>
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase"
                                style={{ background: `${statusColor}22`, color: statusColor }}>
                            {statusLabel}
                          </span>
                        </div>

                        <p className="text-sm" style={{ color: "var(--ink)", lineHeight: 1.5, margin: 0 }}>
                          {sentence}
                        </p>

                        {chips && (
                          <div className="flex gap-3 flex-wrap text-xs mt-1.5">
                            {chips.map((c) => (
                              <span key={c.label} style={{ color: c.passed ? "var(--positive)" : "var(--negative)" }}>
                                {c.passed ? "✓" : "✗"} {c.label}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
              )}
            </div>
          </div>
        )}

        {mainPanelTab === "log" && (
        <div className="flex flex-col">
          {(() => {
            const displayLogs = logPaused ? logSnapshotRef.current : logs;
            const networkLogs  = displayLogs.filter((e) => isNetworkLog(e));
            // Signal outcome lines (SIGNAL_ENTERED/SIGNAL_BLOCKED) are shown in the
            // structured journal section above instead — filtered out here so they
            // don't appear twice in the same tab.
            const thinkingLogs = displayLogs.filter((e) =>
              !isNetworkLog(e) && e.event !== "SIGNAL_ENTERED" && e.event !== "SIGNAL_BLOCKED"
            );
            const netHasError = connectionHealthView(connectionHealth, { failed: connectionCheckFailed }).hasIssue;
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
                            <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-red-500 align-middle" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {logPaused && (
                    <span className="badge badge-blue text-[9px] animate-pulse mr-2">⏸ PAUSED</span>
                  )}
                </div>

                {logTab === "network" && (
                  <ConnectionStatus health={connectionHealth} checking={checkingConnections}
                    failed={connectionCheckFailed} onRefresh={() => void refreshConnections()} />
                )}

                {/* Ticker filter — the structured summary/chips/journal rows
                    that used to live here now live on the Board tab instead;
                    this is purely the raw scrolling narrative, filterable and
                    with repeated "no setup" filler collapsed so it's actually
                    readable instead of a wall of near-identical lines. */}
                <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
                  {logTab === "network" && (
                    <p className="text-[10px] mb-1.5" style={{ color: "var(--ink-muted)" }}>
                      Event history · Earlier errors stay here, even after a connection recovers.
                    </p>
                  )}
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
      </div>

      {/* ── News feed ───────────────────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <button
          type="button"
          className="w-full px-3 py-2.5 flex flex-wrap items-center gap-2 text-left hover:bg-muted transition-colors"
          onClick={() => setNewsExpanded((open) => !open)}
          aria-expanded={newsExpanded}
        >
          <Newspaper size={14} style={{ color: "var(--ink-muted)" }} />
          <span className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--ink-muted)" }}>Market Context</span>
          <span className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
            {newsArticles.length} headline{newsArticles.length === 1 ? "" : "s"} for {newsSymbols}
          </span>
          {!newsExpanded && newsArticles[0]?.headline && (
            <span className="text-xs truncate ml-2" style={{ color: "var(--ink-muted)", flex: 1 }}>
              {newsArticles[0].headline}
            </span>
          )}
          <span className="text-[10px] ml-auto" style={{ color: "var(--ink-faint)" }}>via Alpaca</span>
          <ChevronDown size={14} style={{
            color: "var(--ink-muted)",
            transform: newsExpanded ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 160ms ease",
          }} />
        </button>
        {newsExpanded && (
        <div className="flex flex-col divide-y border-t" style={{ borderColor: "var(--border)" }}>
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
        )}
      </div>
        </aside>
      </div>
    </div>

    {/* ── Trade log drawer ──────────────────────────────────────────────────── */}
    {tradeDrawerId !== null && (() => {
      const trade = openTrades.find((t: Trade) => t.id === tradeDrawerId);

      // Education is defined only for the reviewed production strategies.
      const STRAT_EDU: Record<string, { name: string; setup: string; watch: string; manage: string; color: string }> = {
        V2_ORB_PULLBACK: {
          name: "TSLA Opening-Range Pullback", color: "#eab308",
          setup: "After the 9:30–9:45 opening range is complete, TSLA breaks the range and returns for its first one-minute retouch.",
          watch: "The broken range boundary, first retouch, VWAP side, and completed one-minute confirmation must agree.",
          manage: "The reviewed profile uses the selected contract's next ask and a same-contract executable-bid exit after 90 minutes, with account safeguards.",
        },
        V2_SPY_TREND_CONT: {
          name: "SPY Trend Continuation", color: "#8b5cf6",
          setup: "SPY trend structure pauses, then a completed five-minute candle proves continuation in the established direction.",
          watch: "EMA structure, VWAP side, the mini-range break, and the recorded structural invalidation.",
          manage: "The reviewed profile enters on the next available option ask and measures the same contract's bid after 30 minutes.",
        },
        V2_SPY_AFTERNOON_FVG: {
          name: "SPY Afternoon Fair Value Gap", color: "#06b6d4",
          setup: "Between 1:30 and 3:00 PM ET, SPY creates a qualifying three-candle imbalance and returns to it for the first time.",
          watch: "The gap zone, favorable-half retest close, EMA 8/20 direction, and VWAP agreement.",
          manage: "The reviewed profile enters at the next option ask and measures the same contract's bid after 30 minutes.",
        },
        V2_TSLA_TWO_LEG_TREND_PULLBACK: {
          name: "TSLA Two-Leg Trend Pullback", color: "#3b82f6",
          setup: "TSLA trends on one-minute bars, forms two controlled counter-trend legs, and resumes with VWAP and EMA alignment.",
          watch: "Distinct pullback legs, the recovery between them, VWAP integrity, and the completed resumption candle.",
          manage: "The reviewed profile enters on the next option ask and measures the same contract's executable bid after 90 minutes.",
        },
        V2_FAILED_OR_BREAK_VWAP_REVERSION: {
          name: "SPY Failed-Range Recovery", color: "#2563eb",
          setup: "SPY completes a meaningful opening-range break, then an opposite-color one-minute candle closes back inside before noon with room to VWAP.",
          watch: "The fixed 9:30–9:44 range, the completed outside close, failed-break extreme, recovery close, and remaining room to session VWAP.",
          manage: "After chart proof, one exact 7–21 DTE contract receives a recorded working limit, price ceiling, quantity, and same-contract 30-minute exit.",
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
