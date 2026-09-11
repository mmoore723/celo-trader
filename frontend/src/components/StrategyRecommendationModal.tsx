import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";

export function StrategyRecommendationModal() {
  const [dismissed, setDismissed] = useState("");
  const { data } = useQuery({queryKey: ["strategy-recommendations"], queryFn: api.settings.recommendations, refetchInterval: 60_000});
  const items = data?.recommendations ?? [];
  const fingerprint = items.map(item => `${item.strategy_id}:${item.ticker}:${item.kind}:${item.fingerprint}`).join("|");
  if (!items.length || fingerprint === dismissed) return null;
  return <aside className="fixed bottom-12 right-4 z-50 card p-4 max-w-sm" role="status" aria-label="Strategy recommendations">
    <strong className="text-sm">{items.length} strategy recommendation{items.length === 1 ? "" : "s"} to review</strong>
    <p className="text-xs mt-1">New matches and active pairs that need attention. Your trading choices have not changed.</p>
    <div className="flex gap-2 mt-2"><Link className="btn btn-primary" to="/settings?tab=general" onClick={() => setDismissed(fingerprint)}>Review in Settings</Link><button className="btn btn-ghost" onClick={() => setDismissed(fingerprint)}>Later</button></div>
  </aside>;
}
