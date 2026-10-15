import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";

export function StrategyRemoval({ id, version, name, removed = false }: {
  id: string; version: string; name: string; removed?: boolean;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function change() {
    if (!window.confirm(removed
      ? `Restore ${name} v${version}? Previous switches and approvals will apply again.`
      : `Remove ${name} v${version} from your account in paper and live? New entries and new research tests stop. Open positions keep their exits and history is preserved.`)) return;
    setBusy(true); setError("");
    try {
      await api.settings.removeStrategy(id, version, !removed);
      await Promise.all(["strategy-removals", "strategy-catalog", "tested-strategies", "strategy-recommendations", "admin-strategy-controls", "strategy-research-results", "strategy-research-analytics", "strategy-research-matrix"].map(key => qc.invalidateQueries({ queryKey: [key] })));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update strategy"); }
    finally { setBusy(false); }
  }
  return <div className="mt-2">
    <button type="button" className="btn btn-ghost text-xs" disabled={busy} onClick={change}>
      {busy ? "Saving..." : removed ? "Restore strategy" : "Remove strategy"}
    </button>
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function RemovedStrategies() {
  const { data, isError } = useQuery({ queryKey: ["strategy-removals"], queryFn: api.settings.strategyRemovals });
  const removed = data?.strategies.filter(row => row.removed) ?? [];
  if (isError) return <p className="text-xs" role="alert">Retired strategy archive unavailable.</p>;
  if (!data?.can_restore) return null;
  return <details className="text-xs p-2" style={{ color: "var(--ink-muted)" }}>
    <summary className="cursor-pointer">Retired strategy archive ({removed.length})</summary>
    <p className="text-xs mt-2">No new entries or research tests. Existing positions and history are preserved. Restore reapplies previous switches and approvals.</p>
    {removed.map(row => <div className="mt-3" key={`${row.strategy_id}:${row.version}`}>
      <span>{row.display_name} · v{row.version}</span>
      <StrategyRemoval id={row.strategy_id} version={row.version} name={row.display_name} removed />
    </div>)}
  </details>;
}

export function ResearchTargetTickers() {
  const { data, isError } = useQuery({ queryKey: ["strategy-removals"], queryFn: api.settings.strategyRemovals });
  return <details className="card p-3">
    <summary className="cursor-pointer font-semibold">Research target tickers ({data?.research_tickers.length ?? 0})</summary>
    <p className="text-xs mt-2">Research strategies scan this shared universe. A strategy still needs its own setup conditions and sufficient data. This is not a list of profitable tickers or permission to trade them.</p>
    {isError ? <p role="alert">Could not load research tickers.</p> : <p className="text-xs mt-2">{data?.universe_source === "startup_fallback" ? "Startup universe, no active scanner list yet: " : "Current scanner universe: "}{data?.research_tickers.join(", ") ?? "Loading..."}</p>}
  </details>;
}
