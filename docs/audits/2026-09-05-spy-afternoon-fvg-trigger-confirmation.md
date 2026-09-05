# SPY Afternoon FVG trigger-confirmation repair audit

Date: September 5, 2026

## Decision

Add one causal paper-entry guard: a bullish FVG retest must close above EMA8,
and a bearish retest must close below EMA8. Keep the fixed 30-minute exit and
all other reviewed settings unchanged. This is a paper repair that needs fresh
forward validation; it is not proof that the strategy is ready for live money.

## Defect

The 2.0.0 rule required EMA8/EMA20 trend alignment and the correct side of
session VWAP, but it did not require the trigger candle itself to remain on the
trade side of EMA8. Recent saved candidates therefore included bullish entries
after a strongly bearish retest candle and bearish entries after a strongly
bullish retest candle.

The older generic price-action reports also had a clock error for this study.
The paid option report labels a completed 13:30--13:34 five-minute candle as
13:34 so the execution engine can enter at 13:35. Comparing a bucket's 13:35
close directly to the 13:34 label omitted the trigger candle and described the
prior bucket. The new audit includes a bucket when its close is no later than
the next-minute entry, which is causal and matches production.

## Reproduction

The reproducible job is
`research/jobs/audit_spy_afternoon_fvg_trigger_confirmation.py`.

- Paid markout report SHA-256:
  `9762ce048d048b34fba6672a57434fd9fd1ef26dc0198ecf97eeed85447b7bce`
- One-minute SPY bars SHA-256:
  `a9cfcb0d273881b7831d67b9321653350571b16cce17aed1b83f37c66d748273`
- Input rows: the 23 non-overlapping 30-minute actual ask-to-bid fills from
  `live_baseline_0_50_atr`
- Cost model: add $0.01 adverse entry slippage, subtract $0.01 adverse exit
  slippage, and charge the current platform assumption of $0.65 per side
- No midpoint prices or invented missing quotes

## Results

| Rule | Trades | Wins | Net P&L | Median P&L | After-cost PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing 2.0.0 trigger | 23 | 16 | +$454.10 | +$17.70 | 3.11 |
| EMA8-confirmed trigger | 19 | 13 | +$261.30 | +$7.70 | 2.22 |
| Decisive 60/40 candle close | 8 | 5 | +$182.60 | +$12.20 | 2.56 |

The EMA8 guard has the larger usable sample and remains positive on both sides
of the frozen July 1 split:

| Period | Trades | Wins | Net P&L | Median P&L | After-cost PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| May--June | 11 | 8 | +$168.70 | +$18.70 | 1.89 |
| July holdout | 8 | 5 | +$92.60 | +$6.20 | 4.72 |

Monthly detail is also directionally consistent: May has three wins and no
losses, June PF is 1.64 across eight fills, and July PF is 4.72 across eight.
The stricter 60/40 close-location filter is not selected because it leaves only
eight total fills and would be a more aggressive post-hoc reduction.

## Recent stress evidence

The corrected production snapshot contains eight timely, independent baseline
outcomes through September 4. They total -$171.40 at PF 0.19 under the same
cost model. Six have enough retained scanner candles to replay the trigger.
The EMA8 repair rejects the three largest replayable losses (-$63.30, -$69.30,
and -$26.30) and retains three smaller losses totaling -$51.90. The two baseline
wins predate retained scanner candles, so their repaired-rule eligibility is
unknown and is not invented. This stress evidence explains the repair, but it
cannot be presented as an untouched validation set because the repair was
investigated after these outcomes were visible.

## Limits and next gate

The historical repaired cohort has only 19 fills, with 11 before July. That is
enough to reject the contradictory trigger behavior but not enough to claim
live profitability. The saved strategy switch remains user-controlled. New
exact-contract paper observations must be collected under version 2.1.0, and
the repaired rule should not be called validated until it has at least 20
independent forward fills across at least eight market days, PF at or above
1.50 after costs, positive median P&L, and no newer chronological collapse.
