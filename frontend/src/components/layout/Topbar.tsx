/**
 * Topbar — brand + live bot status strip + theme toggle.
 */
import { Wifi, WifiOff, TrendingUp, TrendingDown, Menu, Moon } from "lucide-react";
import { useBotStore } from "../../store/bot";
import { useUIStore } from "../../store/ui";
import { ThemeToggle } from "./ThemeToggle";
import { formatSignedCurrency } from "../../lib/money.js";
import { useTradingHalt } from "../../hooks/useTradingHalt";

/** Returns true if the US stock market is currently open (ET 9:30–16:00, Mon–Fri). */
function isMarketOpen(): boolean {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay(); // 0=Sun 6=Sat
  if (day === 0 || day === 6) return false;
  const mins = et.getHours() * 60 + et.getMinutes();
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

function isPreMarket(): boolean {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const mins = et.getHours() * 60 + et.getMinutes();
  return mins >= 4 * 60 && mins < 9 * 60 + 30;
}

function fmt(n: number, prefix = "$") {
  const abs = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${prefix}${abs}`;
}

export function Topbar() {
  const halt = useTradingHalt();
  const { status, connected } = useBotStore();
  const { toggleMobileSidebar } = useUIStore();

  const pnl       = status?.session_pnl ?? 0;
  const bal       = status?.account_balance ?? 0;
  const dayOpen   = status?.day_start_balance ?? 0;
  const mode      = status?.mode ?? "paper";
  const running   = status?.running ?? false;
  const brokerConnected = status?.broker_connected ?? false;
  const marketOpen = isMarketOpen();
  const preMarket  = isPreMarket();

  return (
    <header
      className="app-topbar flex items-center px-5 gap-4 border-b"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      {/* Hamburger — mobile only */}
      <button
        className="hamburger-btn btn btn-ghost btn-sm shrink-0"
        style={{ padding: "6px" }}
        onClick={toggleMobileSidebar}
        aria-label="Menu"
      >
        <Menu size={18} />
      </button>

      {/* Brand */}
      <div className="flex items-center gap-2 shrink-0">
        <span
          className="text-base font-bold tracking-tight"
          style={{ color: "var(--accent)" }}
        >
          CELO
        </span>
        <span
          className="text-base font-semibold tracking-widest uppercase"
          style={{ color: "var(--ink)", letterSpacing: "0.18em" }}
        >
          TRADER
        </span>
      </div>

      {/* Divider */}
      <div className="h-5 w-px" style={{ background: "var(--border)" }} />

      {/* Bot status pill.
          FIX 2026-07-17: "LIVE" here used to mean "the bot process is actively
          running" — a completely different thing from the account trading mode
          (PAPER vs LIVE money) shown elsewhere (e.g. the Session P&L card).
          Reusing the word "LIVE" for two unrelated concepts read as a direct
          contradiction ("it says LIVE up top but PAPER down there — which is
          it?"). Account mode is now ALWAYS shown first and unambiguously;
          bot process state is a separate "Running/Idle/Pre-Market/Closed" pill. */}
      <div className="flex items-center gap-2 shrink-0">
        <span className={`badge ${mode === "live" ? "badge-red" : "badge-yellow"}`}>
          {mode.toUpperCase()}
        </span>
        {halt.isError ? <span className="badge badge-red">STATUS UNKNOWN</span> : halt.data?.halted ? <span className="badge badge-red">HALTED</span> : running ? (
          <span className="badge badge-green">RUNNING</span>
        ) : marketOpen ? (
          <span className="badge badge-gray">IDLE</span>
        ) : preMarket ? (
          <span className="badge badge-yellow hidden sm:inline-flex">PRE-MARKET</span>
        ) : (
          <span className="badge badge-gray hidden sm:inline-flex items-center gap-1">
            <Moon size={11} />
            CLOSED
          </span>
        )}
        {/* Strategy ID — desktop only */}
        {status?.last_strategy_id && (
          <span className="text-xs font-mono hidden lg:inline" style={{ color: "var(--ink-muted)" }}>
            {status.last_strategy_id}
          </span>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Live metrics — compact on mobile, full on desktop */}
      <div className="flex items-center gap-3 md:gap-5 shrink-0">
        <div className="flex flex-col leading-none">
          <span className="text-xs hidden sm:block" style={{ color: "var(--ink-muted)" }}>Current Equity</span>
          <span className="num text-sm font-semibold" style={{ color: "var(--ink)" }}>
            {brokerConnected ? fmt(bal) : "Not connected"}
          </span>
        </div>
        <div className="flex-col leading-none hidden lg:flex">
          <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Day Open</span>
          <span className="num text-sm font-semibold" style={{ color: "var(--ink)" }}>
            {brokerConnected ? fmt(dayOpen) : "—"}
          </span>
        </div>
        <div className="flex flex-col leading-none">
          <span className="text-xs hidden sm:block" style={{ color: "var(--ink-muted)" }}>Account Change</span>
          <span
            className="num text-sm font-semibold flex items-center gap-1"
            style={{ color: pnl >= 0 ? "var(--positive)" : "var(--negative)" }}
          >
            {pnl >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            {formatSignedCurrency(pnl)}
          </span>
        </div>
      </div>

      {/* Connection indicator — desktop only */}
      <div className="hidden sm:flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-muted)" }}>
        {connected && brokerConnected ? (
          <Wifi size={14} style={{ color: "var(--positive)" }} />
        ) : (
          <WifiOff size={14} style={{ color: "var(--negative)" }} />
        )}
        {!connected ? "Reconnecting…" : brokerConnected ? "Bot Live" : "Broker not connected"}
      </div>

      {/* Theme toggle */}
      <ThemeToggle />
    </header>
  );
}
