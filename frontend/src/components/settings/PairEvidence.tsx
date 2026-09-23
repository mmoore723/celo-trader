import type { StrategyResearchMatrix } from "../../lib/api";
import { researchProfitFactorText } from "../../lib/researchPairView.js";
import { settingsPairEvidenceRows } from "../../lib/settingsPairEvidence.js";

export function PairEvidence({ strategy, tradingTickers }: {
  strategy?: StrategyResearchMatrix["strategies"][number]; tradingTickers?: string[];
}) {
  const rows = settingsPairEvidenceRows(strategy?.pairs ?? [], tradingTickers);
  return <details className="text-xs pb-2 mt-1" style={{color: "var(--ink-muted)"}}>
    <summary className="cursor-pointer">Current research by ticker · {rows.length}</summary>
    <div className="max-h-56 overflow-auto mt-2 space-y-2" role="region" aria-label="Ticker research, trading on first then alphabetical" tabIndex={0}>
      {!rows.length && <p>No completed strategy-exit tests yet.</p>}
      {rows.length > 0 && <p>Trading on first · A to Z in each group</p>}
      {rows.map(({ pair, trading }) => <div key={pair.ticker}
        className={`pair-evidence-row ${trading ? "strategy-scope-trading" : "strategy-scope-research"} flex flex-wrap justify-between gap-1 rounded-md p-2`}>
        <div className="flex items-center gap-2"><strong style={{color: "var(--ink)"}}>{pair.ticker}</strong>
          <span className="strategy-scope-badge rounded px-1.5 py-0.5 font-semibold">{trading ? "Trading on" : "Research only"}</span>
        </div>
        <span style={{color: pair.option_results && pair.net_one_contract_pnl < 0 ? "var(--negative)" : undefined}}>PF {researchProfitFactorText(pair.profit_factor, pair.option_results)} · {pair.option_results} completed tests</span>
        <span className="w-full">{pair.recommendation?.independent_trades ?? 0}/20 non-overlapping tests · {pair.recommendation?.qualified ? "Passed review checks" : pair.recommendation?.reasons.join(" · ") || "Collecting results"}</span>
      </div>)}
    </div>
  </details>;
}
