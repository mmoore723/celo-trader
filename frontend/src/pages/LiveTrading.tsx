/**
 * LiveTrading.tsx — Main trading cockpit.
 * Real-time chart, signal alert banner (Bot Focus), open positions, eval log, scanner.
 */
import { useState, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Radio, Bot } from "lucide-react";
import { KChart } from "../components/charts/KChart";
import { useBotStore } from "../store/bot";
import { useUIStore } from "../store/ui";
import { api, type Trade, type OptionsChainRow } from "../lib/api";

const FALLBACK_TICKERS = ["SPY", "QQQ"];

type Period = "1D" | "5D" | "1M" | "3M";

const PERIOD_MS: Record<Period, number> = {
  "1D":  1  * 24 * 60 * 60 * 1000,
  "5D":  5  * 24 * 60 * 60 * 1000,
  "1M":  30 * 24 * 60 * 60 * 1000,
  "3M":  90 * 24 * 60 * 60 * 1000,
};

function barLimitForPeriod(tf: string, period: Period): number {
  const barsPerDay: Record<string, number> = {
    "1Min": 420, "5Min": 90, "15Min": 30, "1Hour": 8,
  };
  const tradingDays: Record<Period, number> = {
    "1D": 3, "5D": 8, "1M": 25, "3M": 70,
  };
  return Math.min(2000, Math.max(40, Math.ceil((barsPerDay[tf] ?? 90) * (tradingDays[period] ?? 3))));
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
  const [logPaused,       setLogPaused]       = useState(false);
  const logSnapshotRef  = useRef<typeof logs>([]);
  const [logTab,         setLogTab]           = useState<"thinking" | "network">("thinking");

  const { status, logs } = useBotStore();
  const { } = useUIStore();
  const qc = useQueryClient();

  const barsRefetchMs = tf === "1Min" ? 15_000 : tf === "5Min" ? 30_000 : 60_000;

  // ── Data queries ────────────────────────────────────────────────────────────
  const { data: bars = [], isLoading: barsLoading } = useQuery({
    queryKey: ["bars", ticker, tf, period],
    queryFn: () => api.market.bars(ticker, tf, barLimitForPeriod(tf, period)),
    refetchInterval: barsRefetchMs,
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
      const today = new Date().toISOString().slice(0, 10);
      return (res?.trades ?? []).filter((t: Trade) =>
        (t.entry_time ?? "").startsWith(today)
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

  // Settings — for signal_only_mode toggle
  const { data: appSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
    refetchInterval: 30_000,
  });
  const signalOnly = appSettings?.signal_only_mode ?? false;

  async function toggleSignalOnly() {
    if (!appSettings) return;
    try {
      await api.settings.save({ ...appSettings, signal_only_mode: !signalOnly });
      qc.invalidateQueries({ queryKey: ["settings"] });
    } catch { /* non-fatal */ }
  }

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

  const visibleFrom = useMemo(() => Date.now() - PERIOD_MS[period], [period]);

  const lastClose = bars[bars.length - 1]?.close ?? 0;
  const orHighRaw  = or?.high ?? 0;
  const orLowRaw   = or?.low  ?? 0;
  const orInRange  = lastClose > 0 && orHighRaw > 0 && orLowRaw > 0
    && Math.abs(orHighRaw - lastClose) / lastClose < 0.15
    && Math.abs(orLowRaw  - lastClose) / lastClose < 0.15;
  const safeOrHigh = orInRange ? orHighRaw : undefined;
  const safeOrLow  = orInRange ? orLowRaw  : undefined;

  const evalLog: any[] = (status as any)?.eval_log ?? [];
  const latestSignal    = evalLog[0] ?? null;
  const scannerColor    = (changePct: number) =>
    changePct >= 0 ? "var(--positive)" : "var(--negative)";

  return (
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

        {/* Auto / Manual execution toggle */}
        <button
          onClick={toggleSignalOnly}
          className="card px-4 py-2.5 flex flex-col gap-0.5 min-w-[130px] text-left transition-colors"
          style={{
            border: signalOnly
              ? "1.5px solid var(--warning)"
              : "1.5px solid var(--positive)",
            cursor: "pointer",
          }}
          title={signalOnly
            ? "Signal-Only mode: bot signals but does NOT place orders. Click to enable Auto-Execute."
            : "Auto-Execute mode: bot places orders automatically. Click to switch to Signal-Only."}
        >
          <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Execution</span>
          <span className="flex items-center gap-1.5 font-semibold text-sm">
            {signalOnly
              ? <><Radio size={13} style={{ color: "var(--warning)" }} /><span style={{ color: "var(--warning)" }}>SIGNAL ONLY</span></>
              : <><Bot  size={13} style={{ color: "var(--positive)" }} /><span style={{ color: "var(--positive)" }}>AUTO</span></>
            }
          </span>
        </button>
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
            <span className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
              {latestSignal.ts}  ·  tap row to copy
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
          <KChart
            bars={bars}
            tf={tf}
            trades={tickerTrades}
            visibleFrom={visibleFrom}
            showVwap={showVwap}
            showVwapBands={showVwapBands}
            showOR={showOR}
            showSwings={showSwings}
            showPositionCard={showPositionCard}
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
          />
        </div>

        {/* Scanner / Chain / Signal History panel */}
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
                      <tr key={t.id}>
                        <td className="font-semibold"
                          style={{ cursor: "pointer", color: "var(--accent)" }}
                          onClick={() => setTicker(t.ticker)}
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

        {/* Bot thinking log */}
        <div className="card flex flex-col">
          {(() => {
            const displayLogs = logPaused ? logSnapshotRef.current : logs;
            const networkLogs  = displayLogs.filter((e) => isNetworkLog(e));
            const thinkingLogs = displayLogs.filter((e) => !isNetworkLog(e));
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
                <div
                  className="flex-1 overflow-y-auto p-2 flex flex-col gap-1 font-mono text-xs"
                  style={{ maxHeight: 280, cursor: logPaused ? "text" : "default" }}
                  onMouseEnter={() => { logSnapshotRef.current = [...logs]; setLogPaused(true); }}
                  onMouseLeave={() => setLogPaused(false)}
                >
                  {activeLogs.slice(0, 80).map((entry, i) => {
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
      </div>
    </div>
  );
}
