# Paper-fill fidelity: repeatable read-only audit

This supplements the daily scorecard; it does not replace broker accounting,
change entry/exit rules, select strategies, or claim a live-ready PF.

## Why this check exists

The September 4 read-only audit of the active admin paper account found 31
closed trades entered after the August 14 strategy reset. Recorded gains were
$970, losses $1,489, net -$519, PF 0.6514. All 31 exit quote rows had missing
bid values. Nearby marks existed, but replacing the missing exit quote with a
nearby quote would not prove the price available at the exit decision. The
stored quote rows also lack market timestamps, so freshness cannot be proven.

At 12:20:16 ET on September 4, the repaired runtime recorded a fresh SPY Trend
Continuation paper fill: two contracts at $4.13 against a $4.16 limit. Trade
209, signal and broker events are linked. At the audit time this trade remains
open; its eventual P&L must not be counted as zero, a win, or a completed test.

## Run

From the production project directory, using its Python:

```sh
venv/bin/python -m research.jobs.audit_fill_fidelity \
  --database user_data/admin/trades_paper.db \
  --settings user_data/admin/settings.json \
  --start 2026-08-14 --end 2026-09-05
```

End is exclusive. Filter is entry date, using the database's Eastern-time
timestamp convention. Paper rows and the explicit active account are required.
The tool does not import the application runtime or call any broker. SQL uses
one read-only transaction; missing paths do not create an empty database.
Only the active account identity is read from Settings; no credentials or
account IDs are printed. Query results cannot be used to write old trade rows.

## Interpretation

- Recorded PF uses closed rows with recorded P&L; missing closed P&L prevents
  a full-sample PF. Empty/no-loss samples have no finite PF reported.
- `trade_rows` counts journal rows, not automatically independent episodes.
- Open rows stay separate; no mark-to-market profit is invented.
- Entry difference = (recorded fill minus saved ask) × contracts × 100.
- Exit difference = (saved bid minus recorded fill) × contracts × 100.
- Both differences are descriptive, not proven latency slippage. A recorded
  quote may be stale or from a different time. The report says freshness is
  unverified, even when a numeric difference can be calculated.
- Missing prices remain null, not zero. The first matching-contract entry/exit
  observation is frozen; later favorable prices or nearby marks never replace it.
- The quote comparison is not proof Tradier would have executed that price.
  [Tradier distinguishes real-time production data from delayed sandbox data](https://docs.tradier.com/docs/market-data).
  [Alpaca documents limits of paper simulation](https://docs.alpaca.markets/us/docs/paper-trading),
  including latency slippage, market impact, queue position and regulatory fees.
- Paper accounting is not after-all-live-cost profitability. No assumed fees
  or second slippage deduction are applied to the recorded broker fills.

## Test and deployment boundary

Focused tests cover account/date/paper isolation, read-only/no-create behavior,
empty/open/missing-P&L samples, duplicate trade and quote rows, NaN, true zero
bids, exact-contract identity, stable quote selection, and P&L arithmetic.
This is three new Python files plus this document. No runtime import/caller,
schema migration, Settings change, frontend change or service restart is
needed. Deploy only this scoped commit; leave the open position under the
unchanged running trading process. Rollback is removal/revert of this audit
addition only; never reset the production database or the unrelated research.
