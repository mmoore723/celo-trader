# Strategy profitability queue — September 9, 2026

## Objective

Iterate through the complete 26-strategy catalog. For every strategy, separate
entry, contract-selection/quote, and exit problems; run a small predeclared
repair; compare chronological and fresh prospective evidence; and leave either
a PF 1.5+ strategy+ticker recommendation with sufficient evidence or a precise
next experiment. Research continues collecting every distinct trigger. Nothing
in this queue grants a paper/live rule change.

This is a continuous catalog loop, not a single-strategy task. Finishing or
improving one strategy does not complete the goal: record its disposition,
advance to the next numbered strategy, and keep iterating until all 26 rows have
been investigated and verified. After row 26, rerank unresolved rows using the
new evidence and begin the next pass instead of stopping.

## Production baseline

- Data window: August 11–September 9, 2026 (21 market days)
- Collected tickers: 79
- Scanner source universe: 6,142 optionable symbols
- Catalog: 26 strategies
- Minimum target: PF 1.5 after modeled execution costs, plus adequate sample,
  positive median and net P&L, acceptable drawdown, and chronological/fresh proof

Small samples are descriptive, not proof. An infinite PF with no losses is not
a validated edge. Mean and median are both reviewed because a few large winners
can make PF or average P&L look better while the typical trade loses.

## Ordered queue

| Priority | Strategy | Current priced evidence | Stage / next action |
|---:|---|---:|---|
| 1 | VWAP Pullback (`V2_VWAP_PULLBACK`) | 90 · PF 0.10 · -$3,140.00 | Preserve the intended 5-minute runtime; diagnose SPY/QQQ entry context without reusing rejected RSI/MACD filters |
| 2 | Trend Continuation (`V2_TREND_CONT`) | 50 · PF 0.06 · -$2,544.00 | Diagnose direction/entry gates; compare exits only where direction works |
| 3 | Turtle Soup Reversal (`V2_TURTLE_SOUP_RTH`) | 22 · PF 0.98 · -$7.60 | Preserve pair differences; validate AAPL, repair SPY separately |
| 4 | SPY Trend Continuation (`V2_SPY_TREND_CONT`) | 10 · PF 0.13 · -$230.00 | Reconcile forward rule with paid PF 1.75 evidence |
| 5 | Fair Value Gap (`V2_FAIR_VALUE_GAP`) | 9 · PF 0.05 · -$339.70 | Entry/contract/exit attribution by ticker |
| 6 | Afternoon Reversal (`V2_AFTERNOON_REVERSAL`) | 8 · PF 0.00 · -$406.40 | Diagnose QQQ and TSLA separately |
| 7 | SuperTrend Reversal (`TV_SUPERTREND_REVERSAL_V4`) | 8 · PF 0.11 · -$541.40 | Check direction first; then contract and exit |
| 8 | Opening Momentum (`V2_OPENING_MOMENTUM_RTH_EXPLORATORY`) | 7 · PF 0.00 · -$636.10 | Diagnose broad one-loss pattern and quote selection |
| 9 | VWAP Pullback 1-Hour KER (`CTX_VWAP_PULLBACK_KER10_LONG`) | 4 · PF 0.00 · -$337.20 | Continue prospective collection; inspect failed entry context |
| 10 | Confirmed Opening-Range Breakout (`V2_ORB_CONFIRMED_BREAKOUT`) | 4 · PF 0.01 · -$454.20 | Diagnose entry/option screen; sample too small for exit selection |
| 11 | SPY Failed-Range Recovery (`V2_FAILED_OR_BREAK_VWAP_REVERSION`) | 4 · PF 12.75 · +$85.80 | Do not trust aggregate PF; reconcile weak long-history evidence by ticker |
| 12 | TSLA Opening-Range Pullback (`V2_ORB_PULLBACK`) | 3 · PF 0.52 · -$141.90 | Collect fresh TSLA proof; inspect losing AAPL/QQQ research pairs |
| 13 | Range Sweep Reclaim Calls (`V2_RANGE_SWEEP_RECLAIM`) | 3 · PF 0.84 · -$7.90 | Collect; separate SPY wins from AMZN loss |
| 14 | Midday Breakdown (`V2_MIDDAY_BREAKDOWN`) | 3 · PF 0.00 · -$230.90 | Entry/contract attribution before exit tuning |
| 15 | Context ORB NR7 / Inside Day (`CTX_ORB_NR7_OR_INSIDE`) | 2 · PF 0.01 · -$60.60 | Collect; compare current broad pairs with historical TSLA slice |
| 16 | Impulse Anchored VWAP Pullback (`V2_IMPULSE_ANCHORED_VWAP_PULLBACK`) | 2 · PF 0.00 · -$83.60 | Entry/option-screen diagnosis |
| 17 | SPY ORB RSI/MACD Short (`V2_SPY_ORB_RSI_MACD_SHORT`) | 2 · PF 0.27 · -$68.60 | Collect; no parameter selection yet |
| 18 | TSLA Two-Leg Trend Pullback (`V2_TSLA_TWO_LEG_TREND_PULLBACK`) | 2 current · PF 0.00 · -$220.60 | First paid exit cycle complete; test gentler protection exploratorily, require new forward proof |
| 19 | Afternoon Compression Breakout (`V2_AFTERNOON_COMPRESSION_BREAKOUT`) | 1 · PF 0.00 · -$36.30 | Collect and verify entry funnel |
| 20 | Context ORB ATR10 (`CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG`) | 1 · PF 0.00 · -$69.30 | Collect and diagnose entry context |
| 21 | Gap Fill (`V2_GAP_FILL_RTH`) | 1 · PF 0.00 · -$1.30 | Collect; too small to tune |
| 22 | SPY Afternoon Fair Value Gap (`V2_SPY_AFTERNOON_FVG`) | 1 current · PF 0.00 · -$30.30 | Reconcile current ticker attribution with paid SPY evidence |
| 23 | VWAP Reversion (`V2_VWAP_REVERSION_RTH`) | 1 · no losses · +$73.70 | Collect; infinite PF is not evidence at n=1 |
| 24 | 1-Hour Bollinger / Keltner Squeeze (`CTX_1H_SQUEEZE_MACD_LONG`) | 0 | Identify entry gates and option-screen coverage |
| 25 | VWAP Pullback 10:30 Displacement (`CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG`) | 0 current | Verify live trigger path against six-outcome paid evidence |
| 26 | EMA Pullback (`V2_EMA_PULLBACK_RTH`) | 0 | Identify entry gates and option-screen coverage |

## Completed cycle: TSLA Two-Leg exits

The armed 3-ATR trail was not promoted. On 75 paired outcomes, trail minus
fixed had mean -$7.80 and median $0 (32 better, 27 worse, 16 unchanged). When
the trail fired, median improvement was +$20 but mean was -$9.92 because a few
large winners were cut early. The later sample had only nine outcomes and a
negative median. Any second exit family is exploratory because that holdout has
now been inspected; it must earn promotion on fresh data after July 31, 2026.

## Cross-queue data repair

The first VWAP Pullback diagnosis exposed a catalog-wide option-collection
defect. Research profiles declare 0–7 DTE contracts, and the squeeze declares
3–5 DTE, but the shared Tradier expiration reader returned only 7–21 DTE.
Consequently, ordinary research could see only the single overlap at exactly
7 DTE, while the squeeze's intended window was impossible. The repair passes
each research profile's explicit DTE window to the market-data client and keeps
the reviewed paper/live default at 7–21 DTE. It also calculates DTE from the
New York market date rather than the EC2 server's UTC date. Historical rows are
not rewritten; future setups will show whether quote coverage improves.

## Queue row 1: VWAP Pullback fidelity check

The current prospective `V2_VWAP_PULLBACK` rule is intentionally evaluated on
completed five-minute candles. That cadence existed when the all-ticker runner
was introduced and remained the default when per-strategy cadence support was
added. A separate paid SPY archive study labeled with the same strategy ID used
one-minute candles, so its results are not interchangeable with the current
five-minute `research.1` evidence and must not be presented as validation of the
live research rule.

That paid one-minute study already tested the unfiltered rule, RSI(14),
MACD(12,26,9), their combination, and broad time-of-day/side contexts. None
passed the chronological gate: the May-June portion had negative mean and
median returns even though July improved. Those filters will not be recycled as
a new repair. Row 1 continues with the current five-minute rule and a separately
predeclared entry-context diagnosis; contract and exit assumptions stay fixed
while entry quality is isolated. The 90-minute prospective results remain the
authoritative current baseline.

## Loop rules

1. Use current production aggregates to pick the highest-information target.
2. Freeze the baseline cohort, costs, split date, and no more than a few causal
   candidates before viewing results.
3. Report sample size, PF, net P&L, mean, median, win rate, drawdown, quote
   coverage, and ticker/regime distribution.
4. Reject leakage, overlapping duplicates, late quotes, or a rule selected on
   its own holdout.
5. Keep collecting when evidence is thin; do not call thin evidence profitable.
6. Update this queue after every completed experiment and continue to the next
   strategy. Never disable a strategy or alter paper/live execution without a
   separately reviewed, explicitly approved promotion.
7. A successful result on one row is a checkpoint, not the goal's completion
   condition. Complete the full 1-through-26 pass, then loop back through every
   unresolved row in evidence-priority order.

## Catalog-wide evidence gate correction

The shared research matrix previously exposed PF, win rate, and net P&L but did
not calculate the mean trade, median trade, or chronological running drawdown.
It could therefore label a pair "working" when a few large winners lifted PF
above 1.5 while the typical trade still lost. The corrected gate requires a
positive median in addition to PF and the existing result/day/chronological
checks. Every ticker pair and every recorded exit/contract comparison now
reports average one-contract P&L, typical one-contract P&L, and the pair's
largest running drop. A high-PF pair with a non-positive median is sent to a
fixed-entry/fixed-contract dynamic-exit experiment instead of being recommended.
