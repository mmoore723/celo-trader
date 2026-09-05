# Production prospective evidence integrity audit

Audited September 5, 2026 against the read-only production database snapshot
`celo_admin_matrix_20260905.sqlite`. No strategy setting or broker state was
changed.

## What was wrong

The Research Results matrix measured every raw router candidate, including
signals that the currently deployed strategy-specific entry rule would reject
and older candidates which lacked enough metadata to reconstruct that rule.
The quote collector also filled every overdue 30/60/90-minute bucket with the
first quote seen after a restart. In the production snapshot, some quotes saved
as a 30-minute result were actually captured as late as 102 minutes after the
entry quote.

Those are real observations at the wrong time. They are not valid fixed-horizon
results and can inflate or depress a strategy's PF.

## Corrected evidence funnel

- 1,213 raw candidate rows.
- 61 candidates remain in the reviewed production strategy/ticker scope after
  excluding out-of-scope research pairs, strategies without an executable exit,
  seven expired/replayed signals, 14 signals rejected by the current SPY Trend
  entry rule, and 12 older SPY Trend signals missing required rule metadata.
- 50 independent prospective episodes remain after freezing the first priced
  candidate for a trigger and removing one overlapping position.
- 37 episodes have a same-contract exit quote captured within five minutes of
  the declared horizon.
- Thirteen apparent outcomes are not scored: one missing 30-minute mark, seven
  late 30-minute marks, and five late 90-minute marks.

The quote model crosses the saved Tradier ask at entry and bid at exit, adds
$0.01 adverse slippage per side, and charges $0.12 per contract per side. It is
still a quote replay, not proof of a Tradier or Alpaca fill.

## Corrected current-scope results

| Strategy | Results / days | PF | One-contract P&L | Finding |
| --- | ---: | ---: | ---: | --- |
| SPY Trend Continuation | 18 / 9 | 17.3955 | +$724.68 | Promising, but under the 30-result and 10-day gates; only three entered-paper episodes have comparable current-rule metadata. |
| SPY Afternoon FVG | 8 / 8 | 0.2031 | -$162.92 | The prospective entry is losing; two wins and six losses. |
| SPY Failed-Range Recovery | 4 / 4 | 0.0000 | -$281.96 | Every timely result lost; direction alone does not survive the option path. |
| TSLA Two-Leg Trend Pullback | 7 / 7 | 0.9501 | -$15.68 | Below target and unstable; five timely 30/60-minute results are too few to justify an exit change. |
| VWAP Pullback 10:30 Displacement | 0 | — | $0.00 | No usable prospective production episode yet. |
| TSLA Opening-Range Pullback | 0 | — | $0.00 | No usable prospective production episode yet. |

Across the 37 measured episodes, the portfolio quote replay has PF 1.9459 over
14 trading days and grows modeled cash from $5,000 to $5,865.76 after costs.
That aggregate is not launch-ready: the median return is -0.4786%, and the
same-broker fill-parity gate remains unproven.

## Action supported by this audit

1. Keep the user-selected paper switches unchanged.
2. Make the production collector refuse to backfill a missed horizon with a
   late quote.
3. Make Research Results apply the currently deployed strategy entry rule,
   exclude stale/replayed signals, and report old or late evidence separately.
4. Continue SPY Trend in paper because its timely quote evidence is promising,
   while accumulating enough same-broker fills.
5. Repair Failed-Range and Afternoon FVG entry/contract behavior before claiming
   they contribute to a 1.5+ portfolio.
6. Do not change the TSLA Two-Leg exit from only five timely alternative-horizon
   results; collect prospective evidence first.
