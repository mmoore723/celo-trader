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
