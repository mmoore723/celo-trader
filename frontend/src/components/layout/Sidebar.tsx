/**
 * Sidebar — navigation + bot start/stop controls.
 */
import {
  Activity, BarChart2, BookOpen, Settings,
  FlaskConical, Newspaper, Power, StopCircle, Skull, CalendarDays,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useBotStore } from "../../store/bot";
import { useUIStore } from "../../store/ui";
import { api } from "../../lib/api";
import { useState } from "react";

interface NavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
}

const NAV: NavItem[] = [
  { label: "Live Trading",  to: "/",           icon: <Activity size={16} /> },
  { label: "Performance",   to: "/performance", icon: <BarChart2 size={16} /> },
  { label: "Trade Journal", to: "/journal",     icon: <BookOpen size={16} /> },
  { label: "Backtest",      to: "/backtest",    icon: <FlaskConical size={16} /> },
  { label: "Playbooks",     to: "/playbooks",   icon: <Newspaper size={16} /> },
  { label: "Daily Brief",   to: "/daily-brief", icon: <CalendarDays size={16} /> },
  { label: "Settings",      to: "/settings",    icon: <Settings size={16} /> },
];

export function Sidebar() {
  const { status } = useBotStore();
  const { mobileSidebarOpen, closeMobileSidebar } = useUIStore();
  const running = status?.running ?? false;
  const [busy, setBusy] = useState(false);

  async function startBot() {
    setBusy(true);
    try { await api.bot.start(); } finally { setBusy(false); }
  }
  async function stopBot() {
    setBusy(true);
    try { await api.bot.stop(); } finally { setBusy(false); }
  }
  async function panicClose() {
    if (!confirm("Panic close ALL positions?")) return;
    setBusy(true);
    try { await api.bot.panic(); } finally { setBusy(false); }
  }

  return (
    <>
      {/* Mobile scrim */}
      {mobileSidebarOpen && (
        <div className="mobile-scrim active" onClick={closeMobileSidebar} />
      )}
    <aside
      className={`app-sidebar flex flex-col border-r overflow-y-auto${mobileSidebarOpen ? " mobile-open" : ""}`}
      style={{ background: "var(--sidebar-bg)", borderColor: "var(--border)" }}
    >
      {/* Nav links */}
      <nav className="flex-1 py-3 px-2 flex flex-col gap-0.5">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={closeMobileSidebar}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "text-accent"
                  : "text-ink-muted hover:text-ink"
              }`
            }
            style={({ isActive }) =>
              isActive
                ? { background: "var(--accent-subtle)", color: "var(--accent)" }
                : { color: "var(--ink-muted)" }
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Bot controls */}
      <div
        className="px-3 py-4 flex flex-col gap-2 border-t"
        style={{ borderColor: "var(--border)" }}
      >
        <p className="text-xs font-semibold uppercase tracking-widest mb-1"
           style={{ color: "var(--ink-faint)" }}>
          Bot Controls
        </p>
        {!running ? (
          <button
            className="btn btn-primary w-full justify-center"
            onClick={startBot}
            disabled={busy}
          >
            <Power size={14} />
            Start Bot
          </button>
        ) : (
          <button
            className="btn btn-ghost w-full justify-center"
            onClick={stopBot}
            disabled={busy}
          >
            <StopCircle size={14} />
            Stop Bot
          </button>
        )}
        <button
          className="btn btn-danger w-full justify-center"
          onClick={panicClose}
          disabled={busy}
        >
          <Skull size={14} />
          Panic Close
        </button>
      </div>
    </aside>
    </>
  );
}
