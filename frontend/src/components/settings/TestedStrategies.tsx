import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { StrategyToggleCard } from "./StrategyToggleCard";

export function TestedStrategies({
  researchIds, onResearchIdsChange,
}: {
  researchIds: string[];
  onResearchIdsChange: (ids: string[]) => void;
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

  return <div className="mt-1" id="tested-strategy-library">
    {runtime.map((strategy) => {
        const enabled = researchIds.includes(strategy.strategy_id);
        return <StrategyToggleCard
          key={strategy.strategy_id}
          separated={false}
          label={strategy.display_name}
          checked={enabled}
          onChange={value => toggle(strategy.strategy_id, value)}
        >
          <p className="text-xs pb-2 -mt-1" style={{ color: enabled ? "var(--warning)" : "var(--ink-muted)" }}>
            {enabled ? "Research only · Testing every collected ticker" : "Research paused"}
          </p>
        </StrategyToggleCard>;
      })}
  </div>;
}
