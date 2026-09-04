import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TestedStrategyInventory } from "../../lib/api";

function Study({ report, data }: { report: string; data: TestedStrategyInventory }) {
  const detail = data.report_details[report];
  return <details className="text-xs py-2">
    <summary className="cursor-pointer">{detail?.title || report}
      {detail?.status === "invalid_or_superseded" && <span style={{ color: "var(--warning)" }}> · Invalid or replaced test</span>}
      {detail?.status === "incomplete" && <span> · Incomplete</span>}
    </summary>
    {detail?.purpose && <p className="mt-2">{detail.purpose}</p>}
    {detail?.decision && <p className="mt-1">Recorded conclusion: {detail.decision.replaceAll("_", " ")}</p>}
    <p className="break-all mt-1" style={{ color: "var(--ink-muted)" }}>Source: {report}</p>
  </details>;
}

export function TestedStrategies({ currentIds }: { currentIds: string[] }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const { data, isPending, isError, refetch } = useQuery({ queryKey: ["tested-strategies"], queryFn: api.settings.testedStrategies });
  const query = search.trim().toLowerCase();
  const rows = (data?.strategies ?? []).filter(row => `${row.display_name} ${row.strategy_id} ${row.tickers.join(" ")}`.toLowerCase().includes(query));
  const other = (data?.other_studies ?? []).filter(report => `${report} ${data?.report_details[report]?.purpose ?? ""}`.toLowerCase().includes(query));
  const lastPage = Math.max(0, Math.ceil(rows.length / 20) - 1);
  const currentPage = Math.min(page, lastPage);
  return <section className="card p-4" id="tested-strategy-library">
    <h3 className="text-sm font-semibold">Tested strategy library</h3>
    <p className="text-xs mt-1 mb-3" style={{ color: "var(--ink-muted)" }}>
      All saved tests, including strategies we rejected or retired. These records do not place orders or mean the strategy is currently running.
    </p>
    {isPending ? <p role="status">Loading tested strategies…</p>
      : isError || data?.unavailable ? <div role="alert" className="text-sm">The library could not be loaded. <button className="btn btn-ghost" onClick={() => refetch()}>Try again</button></div>
      : data && <>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>{data.strategies.length} named strategies and variants · {data.reports_scanned} saved reports</p>
        <label className="text-xs font-medium" htmlFor="strategy-library-search">Find a past test</label>
        <input id="strategy-library-search" className="input w-full mt-1 mb-3" placeholder="Strategy name or ticker…" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} />
        <p className="text-xs mb-2" role="status">{rows.length} named matches{other.length ? ` · ${other.length} other studies` : ""}</p>
        {!rows.length && !other.length && <p className="text-sm">No saved tests match your search.</p>}
        {rows.slice(currentPage * 20, currentPage * 20 + 20).map(row => <details key={row.strategy_id} className="py-3" style={{ borderTop: "1px solid var(--border)" }}>
          <summary className="cursor-pointer text-sm font-medium">{row.display_name}
            <span className="block text-xs font-normal mt-1" style={{ color: "var(--ink-muted)" }}>
              {currentIds.includes(row.strategy_id) ? "Also in current catalog" : "Historical tests"} · {row.tickers.join(", ") || "See studies for ticker scope"} · {row.report_count} report{row.report_count === 1 ? "" : "s"}
            </span>
          </summary>
          <p className="text-xs mt-2 break-all" style={{ color: "var(--ink-muted)" }}>Recorded ID: {row.strategy_id}</p>
          <p className="text-xs my-2" style={{ color: "var(--ink-muted)" }}>Different contracts, exits and test periods stay separate; their PFs are not averaged together.</p>
          {row.reports.map(report => <Study key={report} report={report} data={data} />)}
        </details>)}
        {lastPage > 0 && <div className="flex items-center justify-between gap-2 my-3 text-xs">
          <button className="btn btn-ghost" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
          <span>Page {currentPage + 1} of {lastPage + 1}</span>
          <button className="btn btn-ghost" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button>
        </div>}
        {other.length > 0 && <details className="mt-3" open={Boolean(query)}>
          <summary className="cursor-pointer text-sm font-medium">Other saved studies ({other.length})</summary>
          <p className="text-xs my-2" style={{ color: "var(--ink-muted)" }}>Older reports without an explicit strategy ID are kept here, not omitted.</p>
          {other.map(report => <Study key={report} report={report} data={data} />)}
        </details>}
      </>}
  </section>;
}
