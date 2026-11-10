import { useState } from "react";
import { useBotStore, type LogEntry } from "../store/bot";

/** Read the existing account-scoped stream. Never start a worker or trading. */
export function AdminActivityLog() {
  const logs = useBotStore(state => state.logs);
  const connected = useBotStore(state => state.connected);
  const [snapshot, setSnapshot] = useState<LogEntry[] | null>(null);
  const [search, setSearch] = useState("");
  const [problemsOnly, setProblemsOnly] = useState(false);
  const displayed = (snapshot ?? logs).filter(entry => {
    const text = `${entry.ticker ?? ""} ${entry.event ?? ""} ${entry.message}`.toLowerCase();
    return text.includes(search.trim().toLowerCase()) &&
      (!problemsOnly || ["WARNING", "WARN", "ERROR", "CRITICAL"].includes(entry.level.toUpperCase()));
  });

  return <section className="card p-3" aria-label="Live activity log">
    <div className="flex items-center justify-between gap-2 flex-wrap">
      <h3 className="font-semibold">Live activity log</h3>
      <button className="btn btn-ghost text-xs" onClick={() => setSnapshot(snapshot === null ? [...logs] : null)}>
        {snapshot === null ? "Pause log" : "Resume log"}
      </button>
    </div>
    <p className="text-xs mt-1" role="status" style={{ color: "var(--ink-muted)" }}>
      {connected ? "Activity feed connected." : "Activity feed disconnected. Updates may be missing."}
      {snapshot !== null ? " Display paused; the bot is unaffected." : " Newest events first."}
    </p>
    <div className="flex flex-wrap items-center gap-2 my-3">
      <input className="min-w-0 flex-1 rounded border px-2 py-1 text-sm"
        style={{ background: "var(--panel)", borderColor: "var(--border)" }}
        aria-label="Search activity" placeholder="Search ticker or message"
        value={search} onChange={event => setSearch(event.target.value)} />
      <label className="text-xs flex items-center gap-1">
        <input type="checkbox" checked={problemsOnly} onChange={event => setProblemsOnly(event.target.checked)} />
        Warnings and errors
      </label>
    </div>
    <div className="overflow-y-auto rounded border p-2" style={{ maxHeight: 320, borderColor: "var(--border)" }}
      tabIndex={0} aria-label="Recent activity events">
      {displayed.length === 0 ? <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
        {logs.length === 0 ? "No activity received in this browser session yet." : "No events match these filters."}
      </p> : <ol className="space-y-2 text-xs font-mono">
        {displayed.map((entry, index) => <li key={`${entry.ts}-${index}`} className="break-words" style={{ overflowWrap: "anywhere" }}>
          <span style={{ color: "var(--ink-muted)" }}>{entry.ts || "Time unavailable"} </span>
          <strong>{entry.level} </strong>{entry.message}
        </li>)}
      </ol>}
    </div>
    <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>
      Your account's latest 300 received events. This is not a complete history or confirmation that trading is enabled.
    </p>
  </section>;
}
