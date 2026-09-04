# ADR: keep research off the order scan

Status: approved fix, verification in progress. Date: September 4, 2026.

## Evidence

The production TSLA scanner checked at 10:24:27 and 10:26:26 ET but not
10:25. Replaying its recorded candles found a first two-leg signal on the
10:24 candle, visible at 10:25 only. Median observed scan gap was 116.46 s.
This establishes a missed evaluation, not a guaranteed fill or profit.

## Decision

```
Enabled ticker pairs -> single trading loop -> existing safeguards -> broker
Full watchlist       -> separate read-only research worker -> evidence DB
```

The order loop retries at ten-second boundaries, scans only enabled pairs,
and still manages positions when no pair is enabled. Order/risk/recovery and
strategy implementations are unchanged. Research retains the existing
observers and quote follow-ups; this does not restore the separate historical
strategy library or activate a new strategy.

Research receives an independent state dictionary, dedicated market clients
wrapped with only named read methods, and a copied authenticated context.
One bounded pass per user runs at a time; busy submissions are skipped, not
queued as old work. Every accepted pass visits the entire watchlist. Settings
are pinned during a pass, preventing a concurrent paper/live switch from
writing evidence to the wrong DB. The research context cannot save settings.
Stateful bar evaluators receive a research-only dedupe namespace. Stop and
restart cannot revive an old worker, even when the shared bot stop flag clears.

## Alternatives

* Reorder the old sequential list: smaller diff, but a slow chain lookup still
  blocks the next minute. Rejected because it leaves the demonstrated cause.
* Concurrent trading threads: risks duplicate entries and position updates.
  Rejected; all order operations remain in the original single writer.
* Trade old signals afterward: changes causal entry rules and prices. Rejected.

## Limits and verification

Slow broker/order/recovery calls can still delay the order loop. This is not
a real-time guarantee. `execution_scan` records closed-bar coverage, skipped
bars and stale age. `research_scan` and `research_pass` show ongoing coverage
and duration. Research is prospective at the actual observation time, not a
backdated quote or invented fill. Rate limits and worker latency need live
verification; revisit a prioritized streaming market-data service if scale grows.

Tests: blocked research with the real two-leg evaluator; unchanged latest-bar
and duplicate behavior; enabled-pair scheduling; account/mode isolation;
bounded work; stop/restart; no order methods in research; actual-result
narration; existing order/freshness/recovery/catalog regression suites.

Deploy only this hotfix from baseline 7eb194e. Preserve runtime databases,
credentials and unrelated research. Stage imports/tests using the server's
Python before restart. Roll back this release if startup fails, workers
duplicate, research stops covering tickers, or new scan errors/latency appear.
Compare fifteen minutes of post-release logs; do not call a lack of a valid
signal a failed fill or claim profitability from a timing improvement.
