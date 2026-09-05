import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TestedStrategyInventory } from "../../lib/api";
import { StrategyToggleCard } from "./StrategyToggleCard";

function Study({ report, data }: { report: string; data: TestedStrategyInventory }) {
  const detail = data.report_details[report];
  return <details className="text-xs py-2">
    <summary className="cursor-pointer">{detail?.title || report}</summary>
    {detail?.purpose && <p className="mt-1">{detail.purpose}</p>}
    {detail?.decision && <p className="mt-1">Result: {detail.decision.replaceAll("_", " ")}</p>}
    <p className="break-all mt-1" style={{ color: "var(--ink-muted)" }}>Source: {report}</p>
  </details>;
}

export function TestedStrategies({
  currentIds, researchIds, onResearchIdsChange,
}: {
  currentIds: string[];
  researchIds: string[];
  onResearchIdsChange: (ids: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["tested-strategies", researchIds], queryFn: api.settings.testedStrategies,
  });
  if (isPending) return <div className="mt-2"><p role="status">Loading strategies…</p></div>;
  if (isError || data?.unavailable || !data) return <div className="mt-2" role="alert">
    Strategies could not be loaded. <button className="btn btn-ghost" onClick={() => refetch()}>Try again</button>
  </div>;

  const runtime = data.runtime_research ?? [];
  const runtimeIds = new Set(runtime.map(row => row.strategy_id));
  const savedOnly = data.strategies.filter(row => !runtimeIds.has(row.strategy_id));
  const query = search.trim().toLowerCase();
  const filtered = savedOnly.filter(row =>
    `${row.display_name} ${row.strategy_id} ${row.tickers.join(" ")}`.toLowerCase().includes(query)
  );
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

    <details className="mt-4 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
      <summary className="cursor-pointer text-sm font-medium">Saved tests not yet rebuilt ({savedOnly.length + data.other_studies.length})</summary>
      <p className="text-xs my-2" style={{ color: "var(--ink-muted)" }}>
        These are saved reports, not working strategy code. They stay here so no research is lost.
      </p>
      <label className="text-xs font-medium" htmlFor="strategy-library-search">Find a strategy</label>
      <input id="strategy-library-search" className="input w-full mt-1 mb-3" placeholder="Strategy name or ticker…" value={search} onChange={event => setSearch(event.target.value)} />
      {filtered.slice(0, 30).map(row => <details key={row.strategy_id} className="py-3" style={{ borderTop: "1px solid var(--border)" }}>
        <summary className="cursor-pointer text-sm font-medium">{row.display_name}
          <span className="block text-xs font-normal mt-1" style={{ color: "var(--ink-muted)" }}>
            {currentIds.includes(row.strategy_id) ? "Already active elsewhere" : "Saved test only"} · {row.tickers.join(", ") || "Ticker not recorded"}
          </span>
        </summary>
        {row.reports.map(report => <Study key={report} report={report} data={data} />)}
      </details>)}
      {!query && data.other_studies.slice(0, 30).map(report => <Study key={report} report={report} data={data} />)}
      {filtered.length > 30 && <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>Showing the first 30 matches. Search to narrow the list.</p>}
      {!query && data.other_studies.length > 30 && <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>Showing the first 30 saved studies without a strategy name.</p>}
    </details>
  </div>;
}
