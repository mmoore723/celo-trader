import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReviewedStrategyCatalogEntry } from "../../lib/api";

async function controls() {
  const response = await fetch("/api/settings/strategies/admin-controls", { credentials: "include" });
  if (!response.ok) throw new Error("Could not load admin controls.");
  return response.json() as Promise<{ can_override: boolean; strategies: ReviewedStrategyCatalogEntry[] }>;
}

export function AdminStrategyControls() {
  const qc = useQueryClient();
  const { data, isError, refetch } = useQuery({ queryKey: ["admin-strategy-controls"], queryFn: controls });
  const [sid, setSid] = useState("");
  const [ticker, setTicker] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (isError) return <p role="alert">Admin controls could not load. <button type="button" onClick={() => refetch()}>Retry</button></p>;
  if (!data?.can_override) return null;
  const rows = [...data.strategies].sort((a, b) => a.display_name.localeCompare(b.display_name) || a.version.localeCompare(b.version));
  const selected = rows.find(row => row.strategy_id === sid);
  async function save(enabled: boolean) {
    if (!selected) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/settings/strategies/admin-override", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy_id: selected.strategy_id, strategy_version: selected.version, ticker: ticker.trim().toUpperCase(), enabled }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not save this pair.");
      await Promise.all(["settings", "strategy-catalog", "strategy-recommendations", "strategy-research-matrix", "admin-strategy-controls"].map(key => qc.invalidateQueries({ queryKey: [key] })));
      setMessage(`${ticker.toUpperCase()} ${enabled ? "enabled for paper and live modes. Your current account mode has not changed." : "moved to research only. Existing positions keep their exits."}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save this pair.");
    } finally { setBusy(false); }
  }
  return <section className="card p-4 flex flex-col gap-3" aria-label="Admin strategy override">
    <h3 className="font-semibold">Admin strategy override</h3>
    <p className="text-sm">Enable an exact strategy and ticker without waiting for research qualification. This does not change your account mode, risk limits, or automatic closed-trade PF protection.</p>
    <div className="grid gap-3 md:grid-cols-2">
      <label>Strategy and version<select className="input w-full" value={sid} onChange={event => { setSid(event.target.value); setMessage(""); }}>
        <option value="">Select strategy</option>
        {rows.map(row => <option key={row.strategy_id} value={row.strategy_id}>{row.display_name} · {row.version}</option>)}
      </select></label>
      <label>Ticker<input className="input w-full" value={ticker} maxLength={10} onChange={event => setTicker(event.target.value.toUpperCase())} placeholder="SPY" /></label>
    </div>
    {selected && <p className="text-sm">Trading now: {selected.trading_tickers?.join(", ") || "none"}</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="btn btn-primary" disabled={busy || !selected || !ticker.trim()} onClick={() => save(true)}>{busy ? "Saving..." : "Override and enable"}</button>
      <button type="button" className="btn btn-ghost" disabled={busy || !selected || !ticker.trim()} onClick={() => save(false)}>Move to research only</button>
    </div>
    {message && <p role="status">{message}</p>}
  </section>;
}
