import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export function StrategyRecommendationModal() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["strategy-recommendations"],
    queryFn: api.settings.recommendations,
  });
  const pending = data?.recommendations.find((item) => item.decision === "pending");
  const decision = useMutation({
    mutationFn: (value: "paper_enabled" | "live_enabled" | "observing") =>
      api.settings.setRecommendation(pending!.strategy_id, pending!.ticker, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["strategy-recommendations"] }),
  });

  if (!pending) return null;
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" style={{ background: "rgba(15, 23, 42, 0.62)" }} role="dialog" aria-modal="true" aria-labelledby="strategy-match-title">
      <div className="card w-full max-w-lg p-6" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
        <div className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--accent)" }}>New strategy match</div>
        <h2 id="strategy-match-title" className="text-xl font-semibold" style={{ color: "var(--ink)" }}>
          {pending.display_name} now qualifies for {pending.ticker}
        </h2>
        <p className="text-sm mt-3" style={{ color: "var(--ink-muted)" }}>{pending.evidence_summary}</p>
        <div className="rounded-lg p-3 mt-4 text-sm" style={{ background: "var(--surface-raised)", color: "var(--ink)" }}>
          It is observing only right now. This choice affects only your {pending.account_mode} account, and an admin cannot make it for you.
          {pending.account_mode === "live" && !pending.live_eligible && " This strategy is still under paper validation, so live activation is not available yet."}
        </div>
        {decision.isError && <p className="text-sm mt-3" style={{ color: "var(--danger)" }}>Your choice could not be saved. Please try again.</p>}
        <div className="flex flex-wrap justify-end gap-2 mt-5">
          <button className="btn btn-ghost" disabled={decision.isPending} onClick={() => decision.mutate("observing")}>Keep observing</button>
          {pending.account_mode === "paper" && (
            <button className="btn btn-primary" disabled={decision.isPending} onClick={() => decision.mutate("paper_enabled")}>Enable for my paper account</button>
          )}
          {pending.account_mode === "live" && pending.live_eligible && (
            <button className="btn btn-primary" disabled={decision.isPending} onClick={() => {
              if (window.confirm(`Enable ${pending.display_name} on ${pending.ticker} for real-money trading in your account?`)) decision.mutate("live_enabled");
            }}>Enable for my live account</button>
          )}
        </div>
      </div>
    </div>
  );
}
