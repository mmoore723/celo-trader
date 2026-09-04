# Settings strategy library — September 4, 2026

## Scope

Settings now has General and Strategies tabs. Trading switches, observer controls,
new matches and the tested-strategy library are grouped in Strategies. The active
tab is linkable at `/#/settings?tab=strategies`. Both panels stay mounted so switching
tabs does not discard form or credential drafts. Saving credentials remains separate.

The display-only inventory contains 100 recorded strategy names/variants from 338
saved JSON reports, including lowercase legacy names and uppercase study IDs.
Reports without an explicit ID remain in Other saved studies. Invalid/superseded
reports are labeled; nothing is deleted. These counts are not 100 distinct validated
algorithms. A saved test is not evidence that a strategy is currently running.

No strategy permission, ticker scope, broker, credential, risk setting, entry/exit
rule, trade record or live-money mode is changed by this release. The separate
paper-strategy activation and wider continuous-research work is NOT part of this
deployment. Its unfinished execution changes must not be included accidentally.

## Inventory maintenance

Run `python scripts/build_strategy_inventory.py` in the research workspace after
completing studies, review the generated `config/strategy_research_inventory.json`,
then deploy it with the application. The builder reads JSON and Python ASTs; it
never imports historical strategy implementations or reruns paid studies.
This release does not create a new recurring research job.

Each report keeps its source reference, recorded purpose/conclusion and validity
status. PFs from different tickers, contracts, exits and windows are not averaged
or cherry-picked into an invented single historical PF. Existing reviewed-strategy
PFs remain beside their switches. No raw option archive, personal account data,
credentials or local absolute paths are exported by the builder.

The GET endpoint `/api/settings/strategies/tested` uses the existing session
authentication. It cannot save settings, enable a strategy or access broker keys.

## Release checks

- Clean release checkout excludes pending trading and unrelated research changes.
- 45 focused backend checks passed, including six new inventory/authentication checks.
- Application-only regression set: 330 passed. Full `discover -s tests` does not
  pass in a clean checkout: research tests depend on excluded/uncommitted research
  modules and APIs. 47 research-dependent test modules were excluded explicitly
  from the application-only run; they are not reported as passed.
- Frontend: 37 tests passed (including four real-component library tests), lint
  passed, TypeScript and production build passed.
- No new runtime dependencies or database migrations.
- Before restart: require Alpaca Paper, no positions/open orders/pending recovery,
  clean production tracked files, and unchanged settings/credential fingerprints.
- Deploy only the reviewed Settings/library files and their compiled frontend assets.
- Verify health, authenticated library count, tab/search/expansion/pagination, and
  unchanged trading configuration after restart. Do not submit a test order.

Rollback target before this release: `bfb53bab093673a0902d59058e9e87554d25e5db`.
If the endpoint fails, Settings cannot load, or the dashboard fails health checks,
restore the prior application revision and frontend after confirming it is safe
to restart. Never roll back the trading database over newer fills.

Deployment verification will be appended after the production checks.
