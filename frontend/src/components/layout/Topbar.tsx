/**
 * Topbar — brand + live bot status strip + theme toggle.
 */
import { Wifi, WifiOff, TrendingUp, TrendingDown } from "lucide-react";
import { useBotStore } from "../../store/bot";
import { ThemeToggle } from "./ThemeToggle";

function fmt(n: number, prefix = "$") {
  const abs = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${prefix}${abs}`;
}

export function Topbar() {
  const { status, connected } = useBotStore();

  const pnl   = status?.session_pnl ?? 0;
  const bal   = status?.account_balance ?? 0;
  const mode  = status?.mode ?? "—";
  const running = status?.running ?? false;

  return (
    <header
      className="app-topbar flex items-center px-5 gap-4 border-b"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
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
        <span
          className={`badge ${running ? "badge-green" : "badge-yellow"}`}
        >
          {running ? "LIVE" : mode.toUpperCase()}
        </span>
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
