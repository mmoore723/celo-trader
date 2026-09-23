import { useQuery } from "@tanstack/react-query";
import { api, type StrategyResearchMatrix } from "../../lib/api";
import { StrategyToggleCard } from "./StrategyToggleCard";
import { PairEvidence } from "./PairEvidence";
import { strategyName } from "../../lib/strategyIdentity.js";
import { StrategyIdentity } from "./StrategyIdentity";

export function TestedStrategies({
  researchIds, onResearchIdsChange, researchMatrix, embedded = false,
}: {
  researchIds: string[];
  onResearchIdsChange: (ids: string[]) => void;
  researchMatrix?: StrategyResearchMatrix;
  embedded?: boolean;
}) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["tested-strategies", researchIds], queryFn: api.settings.testedStrategies,
  });
  if (isPending) return <div className="mt-2"><p role="status">Loading strategies…</p></div>;
  if (isError || data?.unavailable || !data) return <div className="mt-2" role="alert">
    Strategies could not be loaded. <button className="btn btn-ghost" onClick={() => refetch()}>Try again</button>
  </div>;

  const runtime = data.runtime_research ?? [];
  const toggle = (strategyId: string, enabled: boolean) => {
    const next = new Set(researchIds);
    if (enabled) next.add(strategyId); else next.delete(strategyId);
    onResearchIdsChange([...next].sort());
  };

  const factorText = (value: number | "infinite" | null | undefined) => value === "infinite" ? "∞" : typeof value === "number" ? value.toFixed(2) : "—";

  return <div className={embedded ? "contents" : "settings-card-grid"} id="tested-strategy-library">
    {runtime.map((strategy) => {
        const enabled = researchIds.includes(strategy.strategy_id);
        const matrixStrategy = researchMatrix?.strategies.find(item => item.strategy_id === strategy.strategy_id);
        const evidence = matrixStrategy?.current_evidence;
        return <StrategyToggleCard
          key={strategy.strategy_id}
          separated={false}
          label={strategyName(strategy.display_name)}
          checked={enabled}
          onChange={value => toggle(strategy.strategy_id, value)}
        >
          {enabled ? <p className="text-xs pb-2 -mt-1" style={{ color: "var(--ink-muted)" }}>
            All tickers · Strategy-exit PF {factorText(evidence?.profit_factor)} · {evidence?.option_results ?? 0} completed tests
          </p> : <p className="text-xs pb-2 -mt-1" style={{ color: "var(--ink-muted)" }}>Paused</p>}
          <StrategyIdentity id={strategy.strategy_id} version={matrixStrategy?.version} tickers={[]} label="Research · All collected tickers" />
          <PairEvidence strategy={matrixStrategy} />
        </StrategyToggleCard>;
      })}
  </div>;
}
