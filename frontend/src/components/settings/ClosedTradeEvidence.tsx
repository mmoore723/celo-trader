import type { ClosedTradeEvidence as Evidence } from "../../lib/api";
import { closedTradeText } from "../../lib/closedTradeView.js";

export function ClosedTradeEvidence({data, strategyId, failed, loading}: {
  data?: Evidence; strategyId: string; failed: boolean; loading: boolean;
}) {
  const strategy = data?.strategies.find(s => s.strategy_id === strategyId);
  const pairs = strategy?.pairs ?? [];
  return <div className="text-xs pb-2" style={{color: "var(--ink-muted)"}}>
    <strong>Closed {data?.account_mode ?? "account"} trades</strong>
    {failed ? <p role="status">Trade results could not load. Retrying automatically.</p>
      : loading ? <p>Loading trade results…</p>
      : !data?.available ? <p>Connect an account to see its trade results.</p>
      : <>
        {pairs.map(pair => <p key={pair.ticker} style={{color:
          (pair.realized_pnl ?? 0) < 0 ? "var(--negative)" : undefined}}>{closedTradeText(pair)}</p>)}
        <details className="mt-1">
          <summary className="cursor-pointer">Trade dates and counts</summary>
          <p>v{strategy?.version} · Recorded journal P&amp;L, not research estimates. Partial exits count as one trade after the whole position closes.</p>
          {pairs.map(pair => <div key={pair.ticker} className="mt-1">
            <p>{pair.ticker}: {pair.first_entry_date && pair.last_exit_date
              ? `${pair.first_entry_date} through ${pair.last_exit_date}` : "No completed current-version results"}</p>
            {!!pair.exclusions.different_or_unknown_version && <p>{pair.exclusions.different_or_unknown_version} positions from other or unidentified versions stay in the Journal.</p>}
            {!!pair.exclusions.still_open && <p>{pair.exclusions.still_open} positions still open.</p>}
            {!!((pair.exclusions.incomplete_record ?? 0) + (pair.exclusions.missing_parent ?? 0)) && <p>Some trade records need reconciliation before they can count.</p>}
          </div>)}
        </details>
      </>}
  </div>;
}
