/**
 * Sidebar — navigation + bot start/stop controls.
 */
import {
  Activity, BarChart2, BookOpen, Settings,
  Newspaper, Power, StopCircle, Skull, CalendarDays, ShieldCheck, LogOut,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useBotStore } from "../../store/bot";
import { useUIStore } from "../../store/ui";
import { useAuth } from "../../contexts/AuthContext";
import { api } from "../../lib/api";
import { useState } from "react";

interface NavItem {
  label:     string;
  to:        string;
  icon:      React.ReactNode;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { label: "Daily Brief",   to: "/",            icon: <CalendarDays size={16} /> },
  { label: "Live Trading",  to: "/trading",     icon: <Activity size={16} /> },
  { label: "Performance",   to: "/performance", icon: <BarChart2 size={16} /> },
  { label: "Trade Journal", to: "/journal",     icon: <BookOpen size={16} /> },
  { label: "Learning Hub", to: "/playbooks",   icon: <Newspaper size={16} /> },
  { label: "Settings",      to: "/settings",    icon: <Settings size={16} /> },
  { label: "Admin",         to: "/admin",       icon: <ShieldCheck size={16} />, adminOnly: true },
];

export function Sidebar() {
  const { status, connected } = useBotStore();
  const { mobileSidebarOpen, closeMobileSidebar } = useUIStore();
  const { user, logout } = useAuth();
  const running = status?.running ?? false;
  // True once we've received the first WS status message (status transitions
  // from null → object).  Until then the button is disabled so a reload can't
  // accidentally show "Start Bot" and tempt the user to double-start the bot.
  const statusKnown = status !== null;
  const [busy, setBusy] = useState(false);
  const [controlMessage, setControlMessage] = useState("");
  const entryPermission = useQuery({queryKey:["entry-permission",user?.user_id],
    queryFn:api.bot.entryPermission,refetchInterval:10_000,retry:false});
  async function togglePaperEntries() {
    const permission = entryPermission.data;
    if (!permission || !permission.paper) return;
    if (!permission.enabled && !window.confirm("Resume paper entries with the current strategies, stops and risk limits?")) return;
    setBusy(true);
    try {
      const result = await api.bot.setEntryPermission({...permission,enabled:!permission.enabled});
      setControlMessage(result.message);
      await entryPermission.refetch();
    } catch (error) { setControlMessage(error instanceof Error ? error.message : "Entry permission could not be changed."); }
    finally { setBusy(false); }
  }
  const [opportunitiesSeenAt, setOpportunitiesSeenAt] = useState(() =>
    localStorage.getItem("celo-opportunities-seen-at") ?? ""
  );
  const { data: opportunityData } = useQuery({
    queryKey: ["sidebar-trade-setups"],
    queryFn: () => api.signals.opportunities({ feed: "operational", limit: 50 }),
    refetchInterval: 15_000,
    retry: false,
  });
  const seenMs = opportunitiesSeenAt ? new Date(opportunitiesSeenAt).getTime() : 0;
  const newSetupCount = (opportunityData?.entries ?? []).filter((entry) => {
    const progressed = ["contract_selected", "contract_preview"].includes(String(entry.plan_status));
    const operational = entry.outcome === "entered"
      || progressed
      || (entry.outcome === "pending" && entry.plan_status !== "observation_only");
    const observedMs = new Date(entry.observed_at).getTime();
    return operational && Number.isFinite(observedMs) && observedMs > seenMs;
  }).length;

  function markOpportunitiesSeen() {
    const now = new Date().toISOString();
    localStorage.setItem("celo-opportunities-seen-at", now);
    setOpportunitiesSeenAt(now);
  }

  async function startBot() {
    setBusy(true);
    try { const result = await api.bot.start(); setControlMessage(result.message); }
    catch (error) { setControlMessage(error instanceof Error ? error.message : "Bot could not start."); }
    finally { setBusy(false); }
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
        {NAV.filter(item => !item.adminOnly || user?.is_admin).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={() => {
              if (item.to === "/journal") markOpportunitiesSeen();
              closeMobileSidebar();
            }}
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
            {item.to === "/journal" && newSetupCount > 0 && (
              <span className="ml-auto rounded-full px-1.5 py-0.5 text-[9px] font-bold"
                    style={{ background: "var(--accent)", color: "white" }}>
                {newSetupCount > 99 ? "99+" : `${newSetupCount} NEW`}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Terms of Service link — lets already-accepted users review the disclosure */}
      <div className="px-3 pb-1">
        <NavLink
          to="/terms"
          style={{ fontSize: 11, color: "var(--ink-faint)", textDecoration: "underline" }}
        >
          Terms of Service
        </NavLink>
      </div>

      {/* User / sign-out */}
      <div
        className="px-3 py-2 border-t flex items-center justify-between"
        style={{ borderColor: "var(--border)" }}
      >
        <span className="text-sm font-medium truncate" style={{ color: "var(--ink)" }}>
          {user?.name ?? user?.email ?? ""}
        </span>
        <button
          onClick={logout}
          title="Sign out"
          className="p-1.5 rounded hover:bg-[var(--accent-subtle)] transition-colors"
          style={{ color: "var(--ink-muted)" }}
        >
          <LogOut size={14} />
        </button>
      </div>

      {/* Bot controls */}
      <div
        className="px-3 py-4 flex flex-col gap-2 border-t"
        style={{ borderColor: "var(--border)" }}
      >
        <p className="text-xs font-semibold uppercase tracking-widest mb-1"
           style={{ color: "var(--ink-faint)" }}>
          Bot Controls
        </p>
        {entryPermission.data?.paper && <>
          <p className="text-xs">Paper mode · Entries: {entryPermission.data.enabled ? "On" : "Paused"}</p>
          <button className="btn btn-ghost w-full justify-center" disabled={busy || entryPermission.isFetching}
            onClick={togglePaperEntries}>{entryPermission.data.enabled ? "Pause all entries" : "Resume all entries"}</button>
        </>}
        {entryPermission.isError && <p className="text-xs" role="alert">Entry permission unavailable. Refresh to check.</p>}
        {controlMessage && <p className="text-xs break-words" role="status">{controlMessage}</p>}
        {!statusKnown ? (
          /* WS hasn't sent the first status yet — don't show Start or Stop
             until we know the real bot state to avoid accidental double-starts */
          <button className="btn btn-ghost w-full justify-center" disabled>
            <Power size={14} />
            {connected ? "Loading…" : "Connecting…"}
          </button>
        ) : !running ? (
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
