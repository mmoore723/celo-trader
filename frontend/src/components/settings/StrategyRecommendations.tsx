import type { StrategyTickerRecommendation } from "../../lib/api";

export function StrategyRecommendations({
  recommendations, onDecision,
}: {
  recommendations: StrategyTickerRecommendation[];
  onDecision: (strategyId: string, ticker: string, decision: "paper_enabled" | "live_enabled" | "observing") => void;
}) {
  return <section className="card p-4">
    <h3 className="text-sm font-semibold">New strategy matches</h3>
    <p className="text-xs mt-1 mb-3" style={{ color: "var(--ink-muted)" }}>
      When research finds a strategy that works on a new ticker, choose whether the bot may trade it.
    </p>
    {!recommendations.length ? <div className="rounded-lg p-3 text-xs" style={{ background: "var(--surface-raised)", color: "var(--ink-muted)", border: "1px solid var(--border)" }}>
      No new matches need your answer.
    </div> : recommendations.map(item => <article key={`${item.strategy_id}:${item.ticker}`} className="rounded-lg p-3 mt-2" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><strong className="text-sm">{item.ticker} · {item.display_name}</strong><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{item.evidence_summary}</p></div>
        <span className={`badge ${item.paper_enabled || item.live_enabled ? "badge-green" : "badge-blue"}`}>
          {item.paper_enabled || item.live_enabled ? "ADDED" : item.rollout_stage === "approval_needed" ? "READY" : "RESEARCHING"}
        </span>
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {item.account_mode === "paper" && <button className={`btn ${item.paper_enabled ? "btn-primary" : "btn-ghost"}`} onClick={() => onDecision(item.strategy_id, item.ticker, "paper_enabled")}>Add to paper trading</button>}
        {item.account_mode === "live" && item.live_eligible && <button className={`btn ${item.live_enabled ? "btn-primary" : "btn-ghost"}`} onClick={() => {
          if (window.confirm(`Let ${item.display_name} place live orders on ${item.ticker}?`)) onDecision(item.strategy_id, item.ticker, "live_enabled");
        }}>Add to live trading</button>}
        <button className="btn btn-ghost" onClick={() => onDecision(item.strategy_id, item.ticker, "observing")}>Keep testing</button>
      </div>
    </article>)}
  </section>;
}
