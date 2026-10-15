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
          <summary className="cursor-pointer">What’s included in these results?</summary>
          <p className="mt-1">Closed trades from your Journal{strategy?.version ? ` for v${strategy.version}` : ""}. Not backtests.</p>
          {pairs.map(pair => <div key={pair.ticker} className="mt-1">
            <strong>{pair.ticker}</strong>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt>Counted</dt><dd>{pair.completed_trades} closed {pair.completed_trades === 1 ? "trade" : "trades"}</dd>
              <dt>Dates</dt><dd>{pair.first_entry_date && pair.last_exit_date
                ? `${pair.first_entry_date} to ${pair.last_exit_date}` : "No closed trades yet"}</dd>
              {!!pair.exclusions.still_open && <><dt>Not counted</dt><dd>{pair.exclusions.still_open} still open</dd></>}
              {!!pair.exclusions.different_or_unknown_version && <><dt>Not counted</dt><dd>{pair.exclusions.different_or_unknown_version} from other or unknown versions</dd></>}
              {!!((pair.exclusions.incomplete_record ?? 0) + (pair.exclusions.missing_parent ?? 0)) && <><dt>Not counted</dt><dd>{(pair.exclusions.incomplete_record ?? 0) + (pair.exclusions.missing_parent ?? 0)} incomplete records</dd></>}
            </dl>
          </div>)}
          <p className="mt-2">Partial sells count as one trade when fully closed.</p>
        </details>
      </>}
  </div>;
}
