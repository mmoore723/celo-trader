# Current paper-strategy profitability audit — September 5, 2026

## Scope

This audit joins the signed-in admin account's closed paper trades to the exact
candidate, OCC contract, signal-time Tradier quote, 30/60/90-minute Tradier
marks, and confirmed Alpaca fills stored in the production database. It does
not invent missing prices and does not change any strategy switch.

Modeled Tradier outcomes use one contract, the saved entry ask, the saved
same-contract exit bid, $0.01 adverse slippage per side, and a $0.65 fee per
side. Alpaca outcomes use the broker-confirmed paper fills recorded in the
trade journal.

## Why the aggregate SPY Trend PF is misleading

All 12 accumulated SPY Trend paper trades have PF 0.54 and lost $219, but they
do not represent one rule and one pricing path:

- Five trades predate the candle metadata needed to evaluate the current
  three-candle rule. They are unscorable, not current-version evidence.
- Of seven retrospectively scorable trades, the current rule retains four.
  Those four made $40 at PF 2.11. It rejects three that lost $100 at PF 0.17.
- The repaired three-candle order gate was deployed after the September 4
  market close. Therefore it has zero independent forward broker fills.
- Before the September 1 authoritative order-intent repair, the stored Tradier
  value was an early preview. Some paper fills arrived 25--40 seconds later;
  the largest entry difference was $1.55 per option share.
- On September 4, after authoritative intent was deployed, the three checked
  orders were 0.3--2.0 seconds from the saved Tradier quote and filled at the
  quoted ask or better.

The fix is to identify the materially changed SPY Trend rule as v2.1.0, stamp
that exact version on every future trade, and show current PF only from exact
version matches. Older trades remain visible in Performance as history.

## Enabled strategy diagnosis

| Strategy | Old aggregate result | Current-rule evidence | Diagnosis | Next action |
|---|---:|---:|---|---|
| SPY Trend Continuation | Alpaca PF 0.54, -$219, 12 trades | Retrospective matched subset PF 2.11, +$40, 4 trades; zero post-repair fills | Mixed rule versions plus obsolete quote-preview timing | Collect v2.1.0 forward fills with authoritative intent |
| SPY Afternoon FVG | Alpaca PF 0.22, -$397, 10 trades | EMA8 repair retains six complete Tradier pairs at PF 1.81 and rejects three at PF 0.00; zero post-repair fills | Old rule and old pricing path are mixed into current display | Collect v2.1.0 forward fills; do not count v2.0 history as current proof |
| TSLA Two-Leg | Alpaca PF 2.65, +$355, 6 trades | Directional confirmation retains three scored trades at +$490 and rejects the scored -$15 trade; paid repair PF 2.04; zero post-repair fills | Promising repair, but no independent forward sample | Collect v2.1.0 forward fills |
| SPY Failed-Range | Alpaca PF 0.34, -$214, 6 trades | Tradier PF 0.11 at 30m, 0.14 at 60m, 0.40 at 90m | The entry family is losing; neither broker mismatch nor a longer fixed exit repairs it | Continue research for a distinct entry family; do not data-mine another fixed exit |
| TSLA ORB Pullback | One Alpaca loss | Paid production-style cohort PF 3.24 overall, PF 1.87 older, PF 7.13 later | One trade is too little to overturn the paid evidence | Collect exact current-version forward fills |
| VWAP 10:30 Displacement | No paper trades | Structural paid repair PF 7.21 across only six outcomes | Promising but severely underpowered | Collect v0.2.0 forward fills and preserve structural exit parity |

## Research-only strategies

The historical context strategies are not all losses of the same kind:

- NR7/Inside-Day ORB reached PF 1.70 only in one TSLA $150--$250 slice, while
  broader TSLA, older dates, AMZN, and QQQ were below 1.5. This is a
  ticker/contract-slice instability problem.
- ATR10 ORB and KER VWAP were below PF 1.5 in their largest paid cohorts. Their
  entry filters did not transfer.
- The Bollinger/Keltner squeeze produced no executable option fills, so it has
  no PF to repair yet.
- The prior cross-ticker recorder mixed execution contract rules, account
  affordability, and stale profiles. The deployed `research_contracts_v1`
  pipeline now separates seven real Tradier contract-selection policies and
  excludes old profiles from new PF rather than relabeling them.

The next open-market session must verify that all 23 rebuilt strategies create
fresh, versioned contract observations across the 49 collected tickers. Only
then can ticker-specific promotion or tuning use comparable option evidence.

## Guardrails

- No user strategy switch changed in this audit.
- No strategy is declared profitable from a retrospective subset alone.
- PF at or above 1.5 remains a research target, not a guarantee that $5,000
  will grow to six figures.
- Current-version, same-contract, after-cost forward evidence is the launch
  proof; earlier or unversioned trades remain historical context only.
