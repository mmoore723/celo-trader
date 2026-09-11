import { useState } from "react";
import type { StrategyTickerRecommendation } from "../../lib/api";

export type PairDecision = "enable" | "keep_off" | "research_only" | "keep_trading";
const pf = (value: number | "infinite" | null) => value === "infinite" ? "No losses yet" : value == null ? "—" : value.toFixed(2);

export function StrategyRecommendations({ recommendations, onDecision }: {
  recommendations: StrategyTickerRecommendation[];
  onDecision: (item: StrategyTickerRecommendation, decision: PairDecision) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function decide(item: StrategyTickerRecommendation, action: PairDecision) {
    if (action === "enable" && !window.confirm(`Allow ${item.display_name} to place ${item.account_mode} orders on ${item.ticker}?`)) return;
    if (action === "research_only" && !window.confirm(`Stop new ${item.account_mode} entries for ${item.display_name} on ${item.ticker}? Research and existing-position management continue.`)) return;
    setBusy(true); setError("");
    try { await onDecision(item, action); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save your choice. Try again."); }
    finally { setBusy(false); }
  }
  return <>
    {error && <p role="alert" className="text-sm" style={{color: "var(--negative)"}}>{error}</p>}
    {(["new_match", "review_active"] as const).map(kind => {
      const rows = recommendations.filter(item => item.kind === kind);
      const review = kind === "review_active";
      return <section key={kind} className="card p-4">
        <h3 className="text-sm font-semibold">{review ? "Review active strategies" : "New strategy matches"}</h3>
        <p className="text-xs mt-1 mb-3" style={{color: "var(--ink-muted)"}}>{review
          ? "Pairs appear here when recent tests weaken. Nothing turns off automatically."
          : "Pairs appear here after passing the test checks. You decide whether to allow trading."}</p>
        {!rows.length && <p className="text-xs" style={{color: "var(--ink-muted)"}}>{review ? "No active pairs meet the review trigger." : "No new pairs have passed all checks yet."}</p>}
        {rows.map(item => <article key={`${item.strategy_id}:${item.ticker}`} className="rounded-lg border p-3 mt-2" style={{borderColor: "var(--border)"}}>
          <strong className="text-sm">{item.ticker} · {item.display_name}</strong>
          <p className="text-xs mt-1" style={{color: review ? "var(--negative)" : "var(--positive)"}}>{review
            ? `Latest ${item.completed_trades} non-overlapping tests: PF ${pf(item.profit_factor)} · $${item.net_pnl.toFixed(2)} after costs`
            : `First 14 PF ${pf(item.evidence.training.profit_factor)} · Latest 6 PF ${pf(item.evidence.validation.profit_factor)}`}</p>
          <p className="text-xs mt-1" style={{color: "var(--ink-muted)"}}>Research results—not broker fills. v{item.strategy_version}</p>
          {item.blocker && !review && <p className="text-xs mt-2" style={{color: "var(--warning)"}}>{item.blocker}</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            {review ? <><button disabled={busy} className="btn btn-primary" onClick={() => decide(item, "research_only")}>Move to research only</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_trading")}>Keep trading</button></>
              : <><button disabled={busy || !item.can_enable} className="btn btn-primary" onClick={() => decide(item, "enable")}>Turn on · {item.account_mode}</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_off")}>Keep off</button></>}
          </div>
        </article>)}
        <details className="text-xs mt-3" style={{color: "var(--ink-muted)"}}><summary className="cursor-pointer">What triggers this?</summary><p className="mt-2">{review
          ? "The latest 10 non-overlapping completed research tests have PF below 1.0 and a net loss after costs. Moving to research only stops new entries for this pair, not other tickers or existing-position exits."
          : "20 non-overlapping completed tests: first 14 and latest 6 each need PF 1.5+, the typical result must be positive, and no single winner may supply over 35% of gains. No minimum day count. Every research signal is still collected. These checks do not guarantee future profit."}</p></details>
      </section>;
    })}
  </>;
}
