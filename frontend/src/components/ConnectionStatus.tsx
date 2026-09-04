import type { BrokerConnectionHealth } from "../lib/api";
import { connectionHealthView } from "../lib/connectionHealthView.js";

export function ConnectionStatus({ health, checking, failed, onRefresh, now = Date.now() }: {
  health?: BrokerConnectionHealth;
  checking: boolean;
  failed: boolean;
  onRefresh: () => void;
  now?: number;
}) {
  const view = connectionHealthView(health, { failed, now });
  return (
    <section aria-label="Current connections" className="p-2 border-b flex flex-col gap-1.5" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>
          Current connections{health ? ` · ${health.mode}` : ""}
        </span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRefresh} disabled={checking}>
          {checking ? "Checking…" : "Check now"}
        </button>
      </div>
      {view.verified ? view.connections.map(connection => {
        const healthy = connection.status === "connected";
        const color = healthy ? "var(--positive)" : "var(--negative)";
        return (
          <div key={connection.id} className="text-xs">
            <span aria-hidden="true" style={{ color }}>● </span>
            <span className="font-semibold" style={{ color: "var(--ink)" }}>{connection.label}</span>
            <span style={{ color }}> · {healthy ? "Connected" : connection.status === "missing" ? "Missing credentials" : "Connection failed"}</span>
            <span style={{ color: "var(--ink-muted)" }}> · {connection.purpose}</span>
            {!healthy && <p className="text-xs" style={{ color, margin: 0 }}>{connection.detail}</p>}
          </div>
        );
      }) : (
        <p role="status" className="text-xs" style={{ color: "var(--ink-muted)", margin: 0 }}>
          {checking ? "Checking current connections…" : "Current status unavailable. Check again."}
        </p>
      )}
      {view.checkedAt && (
        <p className="text-[10px]" style={{ color: "var(--ink-faint)", margin: 0 }}>
          {view.verified ? "Checked" : "Previous check"}{" "}
          <time dateTime={view.checkedAt}>{new Date(view.checkedAt).toLocaleString("en-US", {
            timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit",
          })} ET</time>
        </p>
      )}
    </section>
  );
}
