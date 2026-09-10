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
| 1 | VWAP Pullback (`V2_VWAP_PULLBACK`) | 90 · PF 0.10 · -$3,140.00 · mean -$34.89 · median -$28.80 | First pass complete; preserve the 5-minute runtime and prospectively test one 15-minute + 1-hour direction-agreement entry gate without recycling rejected RSI/MACD filters |
| 2 | Trend Continuation (`V2_TREND_CONT`) | 50 · PF 0.06 · -$2,544.00 · mean -$50.88 · median -$39.80 | First pass complete; SPY keeps the entry and prospectively compares 60 minutes plus one loss-tail exit, while QQQ/AAPL need entry repair and TSLA needs post-DTE-fix quote coverage |
| 3 | Turtle Soup Reversal (`V2_TURTLE_SOUP_RTH`) | 22 · PF 0.98 · -$7.60 · mean -$0.35 · median -$13.30 | First pass complete; preserve promising AAPL unchanged, repair SPY separately with one stricter failed-auction entry test, and do not recycle failed fixed holds |
| 4 | SPY Trend Continuation (`V2_SPY_TREND_CONT`) | 10 · PF 0.13 · -$230.00 · mean -$23.00 · median -$16.30 | First pass complete; keep the exact paid-validated rule unchanged because the current SPY cohort is only 3 trades over 2 days and has a positive median |
| 5 | Fair Value Gap (`V2_FAIR_VALUE_GAP`) | 9 · PF 0.05 · -$339.70 · mean -$37.74 · median -$37.30 | First pass complete; QQQ/INTC are entry failures and fixed-hold history supplies no exit repair; keep the separate afternoon FVG hypothesis separate |
| 6 | Afternoon Reversal (`V2_AFTERNOON_REVERSAL`) | 8 · PF 0.00 · -$406.40 · mean -$50.80 · median -$43.30 | First pass complete; reject TSLA transfer as-is, diagnose QQQ entry, and collect SPY/META after the DTE fix |
| 7 | SuperTrend Reversal (`TV_SUPERTREND_REVERSAL_V4`) | 8 · PF 0.11 · -$541.40 · mean -$67.68 · median -$70.80 | First pass complete; current fixed-90m PF does not measure the authored opposite-flip exit, while faithful SPY underlying history is still weak |
| 8 | Opening Momentum (`V2_OPENING_MOMENTUM_RTH_EXPLORATORY`) | 7 · PF 0.00 · -$636.10 · mean -$90.87 · median -$73.30 | First pass complete; current fixed-90m PF ignores the authored 2-ATR trail; collect the intended causal trail before judging exits |
| 9 | VWAP Pullback 1-Hour KER (`CTX_VWAP_PULLBACK_KER10_LONG`) | 4 · PF 0.00 · -$337.20 · mean -$84.30 · median -$85.80 | First pass complete; historical entry evidence already failed and the forward timer does not reproduce the authored prior-high/VWAP structural exit |
| 10 | Confirmed Opening-Range Breakout (`V2_ORB_CONFIRMED_BREAKOUT`) | 4 · PF 0.01 · -$454.20 · mean -$113.55 · median -$135.80 | First pass complete; four outcomes over two days are entry-poor, and the timer also ignores the authored stop/1.5R target |
| 11 | SPY Failed-Range Recovery (`V2_FAILED_OR_BREAK_VWAP_REVERSION`) | 4 · PF 12.75 · +$85.80 · mean +$21.45 · median +$24.20 | First pass complete; keep the exact v2.1 SPY 30m rule collecting—two fresh SPY trades are positive but far below proof and larger history is inconsistent |
| 12 | TSLA Opening-Range Pullback (`V2_ORB_PULLBACK`) | 3 · PF 0.52 · -$141.90 · mean -$47.30 · median -$135.30 | First pass complete; one current TSLA winner is too thin, AAPL/QQQ are unvalidated transfers, and the paid history is profitable only in the later period |
| 13 | Range Sweep Reclaim Calls (`V2_RANGE_SWEEP_RECLAIM`) | 3 · PF 0.84 · -$7.90 · mean -$2.63 · median +$19.70 | First pass complete; preserve two thin SPY winners, diagnose the AMZN entry loss, and collect META after quote-path repair |
| 14 | Midday Breakdown (`V2_MIDDAY_BREAKDOWN`) | 3 · PF 0.00 · -$230.90 · mean -$76.97 · median -$67.30 | First pass complete; QQQ/SPY/TSLA each failed direction on one same-day result, so entry evidence precedes exit tuning |
| 15 | Context ORB NR7 / Inside Day (`CTX_ORB_NR7_OR_INSIDE`) | 2 · PF 0.01 · -$60.60 · mean -$30.30 · median -$30.30 | First pass complete; current evidence is too thin, historical TSLA was unstable, and its structural midpoint/partial exit is not represented by the 90m timer |
| 16 | Impulse Anchored VWAP Pullback (`V2_IMPULSE_ANCHORED_VWAP_PULLBACK`) | 2 · PF 0.00 · -$83.60 · mean -$41.80 · median -$41.80 | First pass complete; SPY direction worked once while QQQ failed once; collect the authored structural 2R exit before judging the 120m comparison |
| 17 | SPY ORB RSI/MACD Short (`V2_SPY_ORB_RSI_MACD_SHORT`) | 2 · PF 0.27 · -$68.60 · mean -$34.30 · median -$34.30 | First pass complete; only two SPY result days exist, so keep collecting the frozen rule without selecting parameters |
| 18 | TSLA Two-Leg Trend Pullback (`V2_TSLA_TWO_LEG_TREND_PULLBACK`) | 2 current · PF 0.00 · -$220.60 · mean -$110.30 · median -$110.30 | First pass complete; first paid exit cycle rejected the aggressive trail, so test gentler protection prospectively and require new proof |
| 19 | Afternoon Compression Breakout (`V2_AFTERNOON_COMPRESSION_BREAKOUT`) | 1 · PF 0.00 · -$36.30 · mean -$36.30 · median -$36.30 | First pass complete; one QQQ result is not tunable and the 12-trade TSLA underlying archive failed the minimum-period sample gate |
| 20 | Context ORB ATR10 (`CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG`) | 1 · PF 0.00 · -$69.30 · mean -$69.30 · median -$69.30 | First pass complete; all historical ticker cohorts were below PF 1.5 and the forward 90m timer does not reproduce the authored structural exit |
| 21 | Gap Fill (`V2_GAP_FILL_RTH`) | 1 · PF 0.00 · -$1.30 · mean -$1.30 · median -$1.30 | First pass complete; authored 2-ATR trail needs faithful collection, but prior SPY train/holdout simulations were both deeply negative |
| 22 | SPY Afternoon Fair Value Gap (`V2_SPY_AFTERNOON_FVG`) | 1 current · PF 0.00 · -$30.30 · mean -$30.30 · median -$30.30 | First pass complete; the result is INTC research, not SPY; preserve the paid-validated SPY v2.1 repair and await fresh SPY evidence |
| 23 | VWAP Reversion (`V2_VWAP_REVERSION_RTH`) | 1 · no losses · +$73.70 · mean +$73.70 · median +$73.70 | First pass complete; one QQQ winner is descriptive and its authored VWAP target/4-ATR stop is not measured by the fixed 90m comparison |
| 24 | 1-Hour Bollinger / Keltner Squeeze (`CTX_1H_SQUEEZE_MACD_LONG`) | 0 | First pass complete; the corrected 3–5 DTE path must now collect the rare rule and its 150% target/20-SMA exit |
| 25 | VWAP Pullback 10:30 Displacement (`CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG`) | 0 current | First pass complete; paid structural PF 7.21 has only six outcomes and one later loss; collect the exact paper exit prospectively |
| 26 | EMA Pullback (`V2_EMA_PULLBACK_RTH`) | 0 | First pass complete; verify the rare 15m/365-EMA funnel and faithfully collect its stop/2.06R exit; paid SPY transfer failed and TSLA holdout had only two outcomes |

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

Its authenticated production aggregate is PF 0.10 over 90 priced outcomes on
only two result days, -$3,140.00 total, -$34.89 mean, and -$28.80 median.
SPY (31 outcomes, PF 0.01, median -$38.30) and QQQ (23, PF 0.13,
median -$36.30) are entry failures; neither was repaired by the recorded
30-minute comparison. TSLA's four same-day outcomes (PF 15.80, median +$61.70)
are descriptive, not a recommendation. The first pass is therefore unresolved:
freeze contract selection and the 90-minute exit, collect the already declared
15-minute + 1-hour direction-agreement variant prospectively, and require at
least 20 priced outcomes across eight result days with PF 1.5+, positive mean
and median, and a passing chronological split.

## Queue row 2: Trend Continuation first pass

The all-ticker `V2_TREND_CONT` uses the same completed five-minute EMA(10/20)
eight-bar breakout premise as the reviewed SPY study, but it is a separate
research identity with a 90-minute comparison. Its current aggregate is PF
0.06 over 50 priced outcomes on two result days, -$2,544.00 total, -$50.88
mean, and -$39.80 median. The sample is large in rows but not in independent
dates, so it cannot support a promotion or a broad rewrite.

SPY is the only current pair where the entry has enough directional support to
isolate the exit: 11 of 18 measured setups moved correctly (61.1%). Its
60-minute result has a positive +$8.20 median but a -$2.08 mean and PF 0.87
over 18 outcomes, which points to a loss-tail problem. Every recorded contract
policy still failed, and 30/90/120-minute exits were worse. QQQ (28.6%
direction), AAPL (18.8%), and AMZN (36.4%) need entry repair instead. TSLA has
only 30.4% usable option coverage and must collect after the DTE-window repair
before its exit is judged.

The paid SPY archive prevents repeated experiments. It already rejected
RSI/MACD gates, 15/60/240-minute alignment, QQQ confirmation, tested candle and
price-structure contexts, a setup ranker, quote-quality filters, discounted
limit entries, alternative contract policies, and the tested Chandelier/
VWAP-EMA dynamic exits. The historical fixed-hold result was also unstable by
period. The next SPY experiment therefore keeps the exact entry and contract
fixed and prospectively compares the 60-minute control with one new causal
loss-tail exit; it cannot be selected from the two current result days. QQQ and
AAPL receive a separately declared entry experiment only after more dates are
available. Row 2 remains unresolved and the queue advances.

## Queue row 3: Turtle Soup Reversal first pass

The aggregate PF 0.98 hides opposite ticker behavior. AAPL has five priced
outcomes on one result day, PF 8.09, +$188.50, +$37.70 mean, +$36.70 median,
and 62.5% direction accuracy. It remains unchanged and collecting; one day is
not proof. SPY has five priced outcomes across two days, 80% direction accuracy,
but PF 0.21, -$69.50, -$13.90 mean, and -$22.30 median, so the current option
result does not monetize the apparently useful direction. QQQ is near flat at
PF 1.02 over five outcomes, with a positive +$10.70 median but only +$0.30 mean.

The 501-outcome paid SPY archive already rejected simply changing the fixed
hold: 30, 60, and 90 minutes all had negative mean and median in both earlier
and later periods. SPY's next test must therefore change the entry evidence,
not recycle a timer. The predeclared repair is one stricter failed-auction
confirmation: preserve the 20-bar sweep/reclaim premise, require a meaningful
ATR-normalized sweep and a confirming reversal close, then hold contract and
exit assumptions fixed. AAPL stays untouched for prospective replication;
missing-chain pairs stay separated from strategy losses. Row 3 remains
unresolved and the queue advances to row 4.

## Queue rows 4–12: reviewed-strategy first pass

`V2_SPY_TREND_CONT` must not be rewritten from its three current SPY outcomes.
They span only two result days, lose $10.90 in total, have a -$3.63 mean, and
retain a positive +$3.70 median. Its exact paid cohort has 46 trades, PF 1.75,
and positive later-month medians under the same 30-minute rule. The one current
larger loss is a reason to keep collecting, not to fit a new rule to three
trades. All previously tested dynamic exits remain rejected.

Generic Fair Value Gap and Afternoon Reversal are current entry problems, not
timer opportunities. Fair Value Gap loses on QQQ and INTC; its paid 30-minute
history was only near break-even and 60/90 minutes were worse. The promising
late-day subset is already represented separately by SPY Afternoon FVG.
Afternoon Reversal has zero wins across four QQQ and four TSLA results on one
day. The paid TSLA transfer failed in both earlier and later periods. SPY's
long early-afternoon subset remains thin and unstable, and META must first
collect usable option quotes after the expiration-window repair.

Rows 7–10 expose a measurement defect that the UI must not hide. SuperTrend's
authored exit is the next opposite SuperTrend flip; Opening Momentum authors a
2-ATR trail with no fixed target; KER authors a prior-high target or completed
VWAP-loss exit; Confirmed ORB authors a structural stop and 1.5R target. The
current matrix instead grades all four with a fixed 90-minute bid. Those marks
remain useful comparisons, but their PF is not the PF of the complete authored
strategy. Faithful underlying SuperTrend history is still weak on SPY, and
KER's historical paid option cohort already failed, so exit fidelity alone is
not evidence of profitability. The repair is to record and label each authored
causal exit before making an exit verdict.

SPY Failed-Range Recovery keeps its exact v2.1 30-minute rule. Its current SPY
pair has only two positive outcomes across two days (+$52.40, +$26.20 mean and
median). The all-ticker PF 12.75 is inflated by four total outcomes and cannot
override the 383-episode long-history result, which failed to maintain PF 1.5
across 2024–2026. Existing 5/10/15-minute and VWAP/structural dynamic exits
were already rejected; they will not be recycled.

TSLA Opening-Range Pullback remains a paper candidate. One current TSLA winner
cannot validate it, while AAPL and QQQ each have one priced research loss and
the other transferred rows predate the universal research selector. Its paid
TSLA history had PF 0.96 in training and PF 1.80 in holdout, but losing months
prevented a durability claim. Fresh post-repair research uses the order-free
0–7 DTE selector on every collected ticker; the historical
`unsupported_v2_ticker` rows are legacy selection failures, not current proof
that cross-ticker collection is still blocked.

## Queue rows 13–18: first pass

Range Sweep Reclaim has a positive +$19.70 median but a negative -$2.63 mean
over only three results, showing one loss dominates two thin SPY wins. AMZN
needs an entry check; META has 66.7% direction across three setups but no
usable chain and must collect after the DTE repair. Midday Breakdown has one
same-day loss each on QQQ, SPY, and TSLA, with 0% measured direction on all
three; it is an entry diagnosis before any exit work.

Context ORB NR7 / Inside Day has only two priced outcomes. Its historical TSLA
slice reached PF 1.70, but broad and chronological evidence failed, and the
current fixed timer does not reproduce its midpoint/partial structural exit.
Impulse Anchored VWAP has one SPY loss despite correct direction and one QQQ
loss with incorrect direction; its authored 2R/structural exit also needs a
faithful option mark rather than relying only on the 120-minute comparison.

SPY ORB RSI/MACD Short has two outcomes over two days at PF 0.27; no parameter
selection is valid. TSLA Two-Leg has already completed its first paid dynamic-
exit cycle: the tested armed trail was not promoted because its later median
was negative and its few large misses outweighed its typical improvements.
Both keep collecting their frozen entries while later experiments remain
prospective.

## Queue rows 19–26: first pass

Afternoon Compression Breakout has one priced QQQ loss. Its frozen TSLA
underlying screen produced only 3 selection, 7 validation, and 2 later trades;
the selection period lost and every period missed the declared 15-trade
minimum. It remains a rare entry hypothesis needing real option evidence.
Context ORB ATR10 also stays observation-only: its largest historical TSLA
cohort had 52 fills at PF 0.95, with SPY 0.53, AMZN 1.04, and QQQ 0.46. The
single current QQQ loss adds no contradictory proof, and the authored
midpoint/partial structural exit still needs faithful collection.

Gap Fill's current QQQ result is nearly flat, but the prior faithful SPY
2-ATR-trail simulation was weak in both periods: training PF 0.18 over six and
holdout PF 0.07 over five. That warns of an entry-family problem in addition
to the matrix's exit-fidelity gap. SPY Afternoon FVG is different: its v2.1
EMA8-confirmed 30-minute repair had 19 paid outcomes, PF 1.89 in training and
PF 4.72 in holdout with positive medians. The lone current loss belongs to an
INTC research transfer; the validated SPY pair has no new result yet and must
remain unchanged while fresh proof accumulates.

VWAP Reversion has one profitable QQQ outcome and no independent basis for a
claim. Its current timer does not reproduce its VWAP target and 4-ATR stop.
The related SPY mean-reversion archive was consistently negative across 81–101
option outcomes, so the single QQQ win is not a reason to loosen or promote the
rule. The exact current entry and authored exit must be collected before any
new tuning family is selected.

The 1-Hour Squeeze has no current setup. Its required 3–5 DTE window was
impossible before the catalog-wide expiration repair; it now needs prospective
collection. Its authored exit is a 150% option target or hourly close back
inside the 20-SMA, not a fixed 90-minute hold. The only analogous TSLA archive
had four 30-minute and two 60/90-minute outcomes, far too few to transfer.

VWAP 10:30 Displacement already has its evidence-matched structural paper exit:
frozen prior-high target, completed five-minute VWAP-loss stop, and 15:55 cap.
Its paid PF 7.21 is based on six outcomes and the single later outcome lost, so
it remains paper-only while exact fresh results collect. EMA Pullback has no
current setup; its 15-minute 365-EMA warmup makes it rare. Paid SPY evidence had
three all-losing outcomes. TSLA's 60-minute history was promising over 16 total
results but had only two later outcomes, so it failed the declared holdout
minimum. Its authored structural stop and 2.06R target need faithful forward
collection.

The complete first pass therefore leaves no honest catalog-wide PF 1.5 claim.
It identifies two distinct next queues: first repair measurement fidelity for
strategies whose authored exits are not recorded; then prioritize adequately
measured entry failures (VWAP Pullback, generic Trend, Afternoon Reversal) for
one prospective causal change each. Paid-validated paper rules remain frozen
until their fresh exact-version cohorts reach the evidence gate.

## Loop two: exit-measurement disclosure

The first loop-back repair inventories the authored exit for all 26 catalog
strategies. Five strategies genuinely use the timer represented by their
matrix PF: Opening-Range Pullback (90 minutes), SPY Trend Continuation (30),
SPY Afternoon FVG (30), SPY Failed-Range Recovery (30), and TSLA Two-Leg Trend
Pullback (90). Their cards now say `30-min PF` or `90-min PF`.

The other 21 strategies currently have only a common 90- or 120-minute option
check in the matrix even though the authored strategy exits by a structural
stop/target, ATR trail, VWAP or opening-range condition, or opposite signal.
Their cards now say `90-min check PF` or `120-min check PF`, and the expanded
evidence names the actual exit followed by `Not measured yet`. The timed check
is retained because it is a useful common comparison; it is no longer
presented as the complete strategy's PF. This disclosure changes no trading or
research rule. Loop two next adds causal collection for those 21 authored exits
instead of selecting repairs from a mislabeled timer.

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
