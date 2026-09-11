import type { StrategyResearchMatrix } from "../../lib/api";
import { researchProfitFactorText } from "../../lib/researchPairView.js";

export function PairEvidence({ strategy }: {strategy?: StrategyResearchMatrix["strategies"][number]}) {
  const pairs = (strategy?.pairs ?? []).filter(pair => pair.option_results > 0 || pair.tradable);
  return <details className="text-xs pb-2 mt-1" style={{color: "var(--ink-muted)"}}>
    <summary className="cursor-pointer">Current research by ticker · {pairs.length}</summary>
    <div className="max-h-56 overflow-auto mt-2 space-y-2">
      {!pairs.length && <p>No completed strategy-exit tests yet.</p>}
      {pairs.map(pair => <div key={pair.ticker} className="flex flex-wrap justify-between gap-1 border-t pt-1" style={{borderColor: "var(--border)"}}>
        <strong>{pair.ticker}{pair.tradable ? " · Trading on" : ""}</strong>
        <span style={{color: pair.option_results && pair.net_one_contract_pnl < 0 ? "var(--negative)" : undefined}}>PF {researchProfitFactorText(pair.profit_factor, pair.option_results)} · {pair.option_results} completed tests</span>
        <span className="w-full">{pair.recommendation?.independent_trades ?? 0}/20 non-overlapping tests · {pair.recommendation?.qualified ? "Passed review checks" : pair.recommendation?.reasons[0]}</span>
      </div>)}
    </div>
  </details>;
}
