# Option price authority repair

## Verified defect

On September4 at13:02ET, Alpaca default and explicit indicative quotes returned
the same exact-contract bid4.11/ask4.13 and timestamp. Explicit OPRA returned403;
Tradier production returned fresh bid4.05/ask4.07. This establishes current feed
selection, not the cause or counterfactual fill of every historical order.

Alpaca documents that default data is indicative without OPRA entitlement,
and indicative quotes are modified. Its paper simulator matches orders against
current NBBO. Availability of the default quote endpoint does not establish
that its returned prices are the simulator's matching prices.

- [Latest option quotes](https://docs.alpaca.markets/us/reference/optionlatestquotes)
- [Option data feeds](https://docs.alpaca.markets/us/docs/historical-option-data)
- [Paper matching and limitations](https://docs.alpaca.markets/us/docs/paper-trading)

The old placement path could replace a strategy-selected Tradier exit bid with
the indicative midpoint/bid. Offline reproduction changed planned4.33 to4.39.
Missing feed provenance, invalid timestamps and even an infinite ask could
also drive repricing. Eight initial regression tests produced13 assertion
failures/subtest failures before the repair.

## Repair and boundaries

- Tradier-authoritative entries retain their initial limit and existing
  risk-approved paper ceiling step without requesting Alpaca quote data.
- Position closes supplied with a Tradier quote explicitly retain that price
  authority. The strategy's bid or midpoint-then-bid policy stays unchanged.
- Other callers may optionally reprice only from explicit OPRA, the exact
  contract, finite valid bid/ask, and an aware timestamp aged0–120seconds.
  This matches the existing exact-contract entry age limit; it rejects a
  replacement quote, not the order. Missing/unavailable OPRA preserves caller
  limits and existing exit urgency. There is no indicative fallback.
- OPRA requests do not buy a subscription. Normal Tradier-authoritative
  entry/close paths no longer need this optional request at all.
- Sell audit references now use bid rather than incorrectly labeling ask.
- Tradier response receive time and bid/ask exchange milliseconds are carried
  into the existing durable execution context for prospective audits. No
  database migration or rewrite of historical quote/trade rows is performed.

Strategy triggers, hold durations, tickers, quantities, entry ceilings, risk
limits, cancellation/recovery behavior, urgent-exit handling, credentials and
paper/live settings are not changed. No real-money trading is enabled.

## Verification and release criteria

New tests cover modified/unknown feeds, wrong contracts, stale/future/naive
timestamps, malformed prices, missing quotes, authoritative buy/sell pricing,
existing live-versus-paper step behavior, feed request parameters and quote
clock forwarding. Existing quote mocks intended to represent valid OPRA now
declare feed/contract/timestamp rather than silently modeling unknown data.

The actual close caller is exercised through durable recovery: its selected
Tradier bid reaches the broker payload, partial fills remain exactly-once, and
quote timestamps survive in the account-scoped recovery record. An AST wiring
check covers the large entry caller; it is not a full entry market simulation.
Broader suites cover account isolation, lost responses, cancel races, emergency
fallback, strategy execution profiles, replay links and research/scan timing.

Deploy only after the complete selected suite passes both locally and on server
Python. Require exact source scope, fresh backups on disk-backed `/var/tmp`,
no current broker/journal/recovery exposure before and after stopping, unchanged
protected settings, then health and15-minute runtime observation. If source
health fails, inspect before rollback; never overwrite new trades with an old DB.

This repair does not guarantee fills, profitable strategies, live/paper parity,
or PF1.5. Quote age in older `option_quote_observations` remains unverified;
new clock evidence lives in execution context, not a backfilled historical table.
The chart redesign and paused historical-strategy release are separate work.
