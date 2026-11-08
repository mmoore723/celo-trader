# Shared market data: in-place repair

## What changes

The existing application uses production Tradier stock data for the trading loop,
forward research worker, strategy-health audit and on-demand backtester. Alpaca
still owns its configured accounts, orders, reconciliation and clock/calendar.
Switches, risk amounts, live status, exit rules and option-order routing are unchanged.
No second bot or parallel strategy implementation was created.

Policy identity: `tradier_consolidated_v1`. The same client methods provide session
candles, historical candles, snapshots and stock quotes. Option selection and normal
option price collection continue using the production Tradier client.

No IEX, Yahoo or delayed sandbox substitution is allowed on this market-data path.
Missing production credentials mean unavailable data. From 09:30 onward on weekdays,
missing current-session bars cannot silently become the previous day's candles.
This includes closing-time collection. Before the open and on weekends, the existing
most-recent-session display behavior remains; holidays with no bars report unavailable.

## Evidence

Bars carry the feed and receipt timestamp; bar event times remain unchanged. Stock
quotes carry feed, receipt and available bid/ask timestamps. Missing timestamps
remain missing. Entry context and observed research candidate metadata include feed
policy. Native historical data no longer receives hardcoded Alpaca labels.

The canonical candle table remains a working read model. A new additive
`scanner_candle_versions` table preserves distinct prior and incoming values, source
and first receipt before canonical replacement. Repeated identical observations are
deduplicated. Source-filtered forward research history excludes legacy Alpaca and
unverified rows instead of relabeling them. Account and paper/live database boundaries
are retained. No historical trade or evidence artifact is rewritten.

Backtest caches are namespaced by feed. The application backtester reports an error
if requested matching history is unavailable or too short; it does not secretly use
Yahoo. Existing legacy scripts explicitly constructing another data client are not
retroactively converted. Historical paid-option reports are not newly validated.

## Known limits

Matching provider is necessary, not proof that research and production signals,
fills or returns are identical. Data can be revised between two fetches; the receipt
and revision records expose this. The legacy backtester still has separately defined
simulation and candle-resolution behavior; no profitability claim is made here.
Current live evidence-source approval guards remain in force. This release does not
authorize live trading or remove the existing premium-plan prerequisite.

Tradier documents consolidated production data and delayed sandbox data at
https://docs.tradier.com/docs/market-data. Its intraday history has finite retention:
https://docs.tradier.com/docs/historical-data. Unsupported windows must be reported,
not filled from another provider. A read-only server check before implementation
returned SPY 1500 five-minute bars, 500 fifteen-minute bars, 100 hourly bars and 220
daily bars. This does not establish open-session freshness or all-ticker coverage.

## Release and rollback

Run focused feed/isolation/provenance tests plus the complete production suite,
frontend lint/build and deploy.sh. Verify GitHub main, production commit, public
frontend hash, services, health, actual data reads and runtime review integrity.
Do not submit test orders. Observe provider latency/errors and worker collection.
If the market is closed, open-session verification remains pending.

Rollback if order delegation changes, protective-exit regressions occur, data calls
fail systematically or service health fails: scoped revert of this release through
deploy.sh to `0019a846178b3e39917faa2111342c97050bd0cb` behavior and runtime review.
Retain the additive candle-revision table and historical records. Do not change saved
strategy switches, risk settings, broker mode or policies on existing positions.
# Follow-up archive isolation, runtime revision 20261107.2

Entry-path inspection found that `strategies/research_orders.py` still loaded
archived one-minute candles without a source constraint. Gap Fill also loaded
unfiltered native five-minute history. These paths could combine pre-cutover
IEX archive rows with current Tradier bars despite the shared broker boundary.

Both archive reads now require `tradier_consolidated_v1`. Old records remain
untouched. A strategy may lack sufficient matching history immediately after
cutover; it must not silently substitute old-feed bars to create a signal.
No exit, threshold, selected policy, switch or account-risk change is included.

Regression tests exercise each generic research-order route, verify exact
account scope and source requirements, and cover both Gap Fill archive reads.
Existing archive tests separately verify foreign-feed exclusion and retention
of historical candle revisions. Full deployment acceptance must pass before
release completion is claimed.

Rollback: revert this follow-up code, test and runtime-review selection through
`deploy.sh` to the db580b3 release. Keep all historical evidence and the new
review manifest. Roll back if runtime integrity or entry routing regresses;
do not treat an honest lack of same-feed warmup as a reason to mix feeds again.
# Capture-only follow-up: November 7, 2026

Approved scope: preserve existing raw levels and underlying last-trade evidence.
No entry, exit, sizing, risk, strategy permission or live-status changes.

The adapter now preserves trade_date and last_volume separately from bid/ask
timestamps. Entry metadata saves the existing previous touch-bar low/high for
VWAP Pullback and the engine's existing pullback extreme for Impulse. Missing
values stay missing. These fields do not become protective stops in this release.

The independent celo-underlying-capture service polls production Tradier GET
quotes every five seconds while positions or saved native deadlines need data.
It reads the active account and mode, records account/mode/trade IDs and raw
source fields in a new append-only underlying_trade_observations table, and
recovers its watch list from saved trades after restart. Repeated retries with
the same receipt timestamp cannot duplicate evidence. SQLite lock waits are
bounded to 200ms. Request timeouts and rate limits produce visible blocked
health with bounded backoff. No execution client is loaded by this worker.

Capture continues for 30 seconds beyond a saved deadline to retain closing-time
observations. Late quotes remain late, never substituted as on-time exit fills.
No candidate horizons are invented. Closed trades missing a saved deadline
are reported and cannot receive an inferred post-exit horizon. Polling is not
every-print tape and the first observation can follow entry by a polling delay.
Prior observations are not rewritten or presented as original-time evidence.

Health is persisted in each user's underlying_capture_health.json and systemd
journal. A successful process start is not proof of fresh market-session data.
Structural levels are frozen entry metadata, not recomputed support/resistance.
The recorded receipt time identifies when this worker received the quote, not
when the trading loop received an earlier quote. Both capture mechanisms remain
distinct. This release does not start or qualify an exit experiment.

Rollback: stop and disable celo-underlying-capture first, revert this release
through deploy.sh to the prior capture-free source c490f731, keep the additive
observation table and historical review manifests. Do not change account settings
or position policies. Roll back capture on repeated worker crashes, sustained
SQLite lock errors or measurable trading/API latency regression.

Verification: focused capture and entry parity regression, then full deploy.sh
acceptance. Saturday checks can verify service/health and deployed source only.
Fresh quotes, real entry metadata and session-close continuity require the next
open session. Existing scheduled verification must check this newer release.
