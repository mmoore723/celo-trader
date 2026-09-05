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

  return <div className="mt-2" id="tested-strategy-library">
    {runtime.map((strategy, index) => {
        const enabled = researchIds.includes(strategy.strategy_id);
        return <StrategyToggleCard
          key={strategy.strategy_id}
          separated={index > 0}
          label={`${strategy.display_name} · v${strategy.version}`}
          checked={enabled}
          onChange={value => toggle(strategy.strategy_id, value)}
        >
          <p className="text-xs pb-1 -mt-1" style={{ color: "var(--ink-muted)" }}>
            <strong style={{ color: "var(--warning)" }}>Historical PF collecting</strong>
            {" · Goal 1.5"}
          </p>
          <p className="text-xs pb-3" style={{ color: "var(--warning)" }}>
            {enabled ? "Researching every collected ticker · No orders" : "Research paused · No orders"}
          </p>
        </StrategyToggleCard>;
      })}
  </div>;
}
