/**
 * Topbar — brand + live bot status strip + theme toggle.
 */
import { Wifi, WifiOff, TrendingUp, TrendingDown, Menu, Moon } from "lucide-react";
import { useBotStore } from "../../store/bot";
import { useUIStore } from "../../store/ui";
import { ThemeToggle } from "./ThemeToggle";

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
  const { status, connected } = useBotStore();
  const { toggleMobileSidebar } = useUIStore();

  const pnl       = status?.session_pnl ?? 0;
  const bal       = status?.account_balance ?? 0;
  const mode      = status?.mode ?? "paper";
  const running   = status?.running ?? false;
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

      {/* Bot status pill */}
      <div className="flex items-center gap-2">
        {running ? (
          <span className="badge badge-green">LIVE</span>
        ) : marketOpen ? (
          <span className="badge badge-yellow">{mode.toUpperCase()}</span>
        ) : preMarket ? (
          <span className="badge badge-yellow">PRE-MARKET</span>
        ) : (
          <span className="badge badge-gray flex items-center gap-1">
            <Moon size={11} />
            MARKET CLOSED
          </span>
        )}
        {status?.last_strategy_id && (
          <span className="text-xs font-mono" style={{ color: "var(--ink-muted)" }}>
            {status.last_strategy_id}
          </span>
        )}
      </div>

      {/* Live metrics */}
      <div className="flex items-center gap-5 ml-2">
        <div className="flex flex-col leading-none">
          <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Balance</span>
          <span className="num text-sm font-semibold" style={{ color: "var(--ink)" }}>
            {fmt(bal)}
          </span>
        </div>
        <div className="flex flex-col leading-none">
          <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Session P&L</span>
          <span
            className="num text-sm font-semibold flex items-center gap-1"
            style={{ color: pnl >= 0 ? "var(--positive)" : "var(--negative)" }}
          >
            {pnl >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            {pnl >= 0 ? "+" : ""}
            {fmt(pnl)}
          </span>
        </div>
        {status?.ticker && (
          <div className="flex flex-col leading-none">
            <span className="text-xs" style={{ color: "var(--ink-muted)" }}>Watching</span>
            <span className="num text-sm font-semibold" style={{ color: "var(--ink)" }}>
              {status.ticker}
            </span>
          </div>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Connection indicator */}
      <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-muted)" }}>
        {connected ? (
          <Wifi size={14} style={{ color: "var(--positive)" }} />
        ) : (
          <WifiOff size={14} style={{ color: "var(--negative)" }} />
        )}
        {connected ? "Live" : "Reconnecting…"}
      </div>

      {/* Theme toggle */}
      <ThemeToggle />
    </header>
  );
}
