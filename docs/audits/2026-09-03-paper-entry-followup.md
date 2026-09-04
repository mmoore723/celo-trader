# September 3, 2026 — paper-entry follow-up

## Bottom line

No orders reached Alpaca on September 3. This was not an order-fill failure:
all nine recorded signal outcomes were blocked before submission and before
the approximately 2:30 PM ET production-token repair. After that cutoff, the
bot continued scanning but recorded no new trade signals. The repaired
connection has not yet been validated by a subsequent complete broker trade.

Audit scope: the admin account, Alpaca Paper, September 3 Eastern time;
production records inspected after the market close. No credentials, broker
selection, trading mode, strategy rules, or risk limits were changed. No test
orders were submitted. The application changes were deployed and verified on
September 3 at 8:03:50 PM ET; see the release verification below.

## Release verification

- Deployed code: `cf8b57b597d7a66ef0c8fcda6eb25821c6519301`, including the
  application patch `8fb9d0e` and a timezone-independent test-fixture correction.
- Previous rollback version: `0126d79f8be753d2d40451404871bac08ed054fe`.
- Release source: the verified private `mmoore723/celo-trader` repository.
  Local main, GitHub, and EC2 were synchronized; unrelated research was excluded.
- The first server-side test run caught a machine-date assumption in the old
  contract-selection test at UTC midnight. The guard restored the previous
  checkout before restarting. The fixture now pins New York time; no contract
  selection or strategy logic was changed to make the test pass.
- Revalidation: 574 backend tests, 33 frontend tests, lint and frontend build
  passed locally; all 65 focused tests then passed on EC2 before restart.
- The restarted service was active/running with zero automatic restarts.
  Both the local and public health endpoints returned healthy.
- Public HTML, entry bundle, Live Trading bundle, Settings bundle, and
  connection-health helper were byte-identical to the tested build. The HTML
  response uses `no-cache, no-store, must-revalidate`.
- Signed-in browser verification showed Alpaca Paper and Tradier Production
  connected with a fresh ET check time; the current Alpaca Settings page had
  the production token field and no unused Sandbox/live-account fields.
- Credential-file fingerprint and strategy/risk settings matched the pre-release
  snapshot. Alpaca Paper remained selected, the bot resumed, and broker positions
  and open orders remained zero. No credential save or trading-control button
  was used during browser verification.
- Initial post-release application event review found only INFO events and no
  recorded WARNING, ERROR, or CRITICAL events. This is a bounded after-hours
  smoke check, not a claim of observed trade execution or a completed live trial.
- The user's completion preference is now recorded in `CLAUDE.md`: approved
  application work includes scoped deployment and verification unless the user
  requests local-only work or a concrete blocker prevents deployment.

Security follow-up: the existing EC2 Git remote embeds a GitHub deployment
token, and it appeared in diagnostic output during repository verification.
Rotate that GitHub token and use secure credential storage; do not copy the
value into this report. No Alpaca or Tradier secret was exposed or changed.

## Recorded signal outcomes

| Time ET | Ticker / strategy | Why no order was submitted |
| --- | --- | --- |
| 9:53:03 AM | SPY / Failed OR Break VWAP Reversion | Exact option quote 911.7 seconds old |
| 10:23:07 AM | TSLA / Two-Leg Trend Pullback | Exact option quote 910.3 seconds old |
| 11:10:07 AM | SPY / Trend Continuation | Exact option quote 1,023.4 seconds old |
| 1:20:05 PM | SPY / Trend Continuation | Exact option quote 902.4 seconds old |
| 1:51:18 PM | SPY / Failed OR Break VWAP Reversion | No usable Tradier option chain |
| 1:53:31 PM | SPY / Failed OR Break VWAP Reversion | No usable Tradier option chain |
| 1:55:48 PM | SPY / Trend Continuation | Existing afternoon FVG slot-reservation rule |
| 1:58:00 PM | SPY / Trend Continuation | Existing afternoon FVG slot-reservation rule |
| 2:20:18 PM | SPY / Afternoon FVG | No usable Tradier option chain |

These are nine signal-journal records (IDs 1251–1259), not nine proven
independent opportunities. Repeated detections are not independent trials.
The three missing-chain records alone do not establish a specific HTTP status;
do not relabel them all as 401s without the matching request evidence.

Read-only sources cross-checked:

- Production admin paper database: `signal_journal`, `broker_order_events`,
  `trades`, `system_events`, and candle data.
- Alpaca's own orders API, status=all, September 3 ET: **zero orders**.
- Broker order events: **zero**. Trade rows for the day: **zero**.
- Current broker positions at audit time: **zero**.
- After 2:30 PM ET: 1,258 system events, all INFO; zero recorded warning,
  error, or critical events. This is absence of recorded errors, not proof
  that every conceivable operation succeeded.
- 530 “No trade setup found” messages between 2:30:54 and 3:45:16 PM ET.
  These are scan messages, not 530 setups or independent research episodes.
- Collection/scanning continued later; the 5:00:19 PM message reported resting
  until the next session.

Date handling: timestamps with offsets were converted to America/New_York;
legacy naive timestamps were treated as Eastern time. The broker query used
04:00 UTC September 3 through 04:00 UTC September 4.

## Data collection check

All 18 observed universe symbols had September 3 candles: AAPL, AMD, AMZN,
DDOG, META, MRK, MRVL, NET, NFLX, NVDA, PLTR, QQQ, SLB, SNOW, SPY, TSLA,
TWLO, ZS. Presence is not completeness: counts range from 202 (TWLO) to 406
(QQQ), include some extended-hours bars, and do not establish complete
one-minute regular-session coverage. Option-chain/quote coverage for every
symbol and every minute was not established by this candle check.

## Changes and regression results

- Network warnings now depend on a fresh connection check, not any old ERROR
  still present in the log. The actual log history is preserved.
- Current connections show an Eastern-time check timestamp and refresh each
  minute while the Network tab is open. Failed refreshes and old results show
  unknown status instead of stale “Connected.”
- Unused Sandbox controls and status rows are hidden for the current Alpaca
  route. No saved credential is removed. Tradier Paper remains a separate,
  explicitly selected configuration.
- Paper timeout logs no longer promise a market retry when it is disabled.
- Execution summaries distinguish actual partial fills from complete fills.
  This changes reporting, not submitted quantities, prices, or execution rules.

New backend replays cover delayed/missing/malformed quote ages, partial entry,
partial exit, fill-during-cancel races, emergency-exit remainder sizing and
weighted fill price, and blocking a replacement when cancellation is unknown.
An integrated offline replay connects real contract selection, order handling,
partial-fill quantity, exit handling, and database P&L. Broker responses are
fixtures, not fabricated production evidence.

The new tests first reproduced two failures: misleading market-retry text and
a partial fill mislabeled as complete. Both passed after the reporting fixes.

| Check | Result |
| --- | --- |
| Focused backend lifecycle/quote/connection suites | 65 passed |
| Full application backend suite (`unittest discover -s tests`) | 574 passed |
| Frontend tests, including actual connection-component rendering | 33 passed |
| Frontend lint | Passed |
| TypeScript and production frontend build | Passed |
| Whitespace/diff check | Passed |

The focused 65 are included in the 574, not additional tests. The independent
`research/tests` universe and paid-data strategy sweeps were not rerun: no
strategy/research change is part of this patch. Negative-path test logs include
deliberately injected failures; the runner completed successfully. One existing
test emitted an unclosed-SQLite ResourceWarning.

## Remaining validation — do not call this live-ready

1. **Next qualifying paper trade:** reconcile the recorded exact option quote,
   approved price ceiling, submission, replacement IDs, actual fill quantity
   and price, exit, and journal P&L against Alpaca. No forced trade just to
   obtain a green test. Actual fill rate/slippage today is **not measurable**
   from zero submitted orders.
2. **Cost realism:** `database/trades.py::close_trade` currently deducts its
   configured commission allowance only for live-mode rows. Paper P&L is not
   a like-for-like live net-profit estimate. Keep broker paper accounting
   separate from a fee/slippage-adjusted research result; validate the fee
   schedule before changing that model. Existing paper results were not
   recomputed here.
3. **Ambiguous broker outcomes:** an unconfirmed cancellation blocks a market
   replacement and raises an issue. Current code returns no confirmed result
   in that branch, even if a partial fill was observed while cancellation was
   pending. Durable recovery/reconciliation of that exposure remains a safety
   follow-up, as does a partially filled emergency fallback that never reports
   a final complete fill. The new tests do not certify automatic recovery from
   every broker outage/restart race. These were code-review findings, not
   September 3 production incidents (there were no orders).
4. **Collection completeness:** quantify regular-session bar and exact-option
   quote gaps before claiming watchlist-wide replay coverage.

No missed-opportunity profit, win rate, or profit factor can honestly be
computed from these nine blocked records alone.

## Review and references

Scoped review: changes preserve paper routing, limit-order protections,
credentials, and historical evidence. No new service or external dependency
was added. Remaining execution-recovery gaps above are not closed by a UI
cleanup or by passing offline regression tests.

[Alpaca order documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
describes partial fills, order state, and why limit orders may remain unfilled.
[Tradier market-data documentation](https://docs.tradier.com/docs/market-data)
distinguishes delayed sandbox data from production market data. See the
[pricing runbook](../runbooks/tradier-paper-pricing.md) for the credential and
read-only verification procedure.
