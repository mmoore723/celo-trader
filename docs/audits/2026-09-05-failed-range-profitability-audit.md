# SPY Failed-Range Recovery profitability audit

## Decision

Do not claim that SPY Failed-Range Recovery is profitable. Its original paid
option study passed on 21 trades, but the much larger SPY history and the
independent paper evidence do not confirm that result. The user's strategy
switch remains unchanged while the bot is in paper mode.

The reproducible long-history job is
`research/jobs/audit_spy_failed_range_generalization.py`. Its reviewed summary
is frozen in the versioned strategy evidence manifest; the job checks the
source hash and the exact 383-row reference totals before a regenerated report
can be used.

This release fixes one implementation-parity defect: production now excludes
premarket and postmarket bars from this strategy's VWAP, ATR, and candle
context. The paid historical study used 09:30–16:00 ET bars only.

## Evidence

The original paid OPRA result used actual option asks at entry and the same
contract's bid after 30 minutes:

| Evidence set | Trades | PF | Result |
| --- | ---: | ---: | --- |
| May–July paid option study | 21 | 3.0364 | Promising but small |
| Current timely Tradier quotes | 4 | 0.0000 | Four losses; failed forward check |

The unchanged signal was then screened on 383 regular-session SPY episodes
from January 2024 through July 2026, entering at the next one-minute open,
exiting 30 minutes later, and subtracting a 0.02% round-trip underlying cost
allowance:

| Period | Trades | Wins | Net directional return | PF |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 139 | 78 | +1.6553% | 1.183 |
| 2025 | 160 | 71 | -1.8297% | 0.885 |
| Jan–July 2026 | 84 | 42 | +0.7006% | 1.082 |

This underlying screen is not an option-profit backtest, but a strategy that
cannot preserve a directional edge at the underlying level is not repaired by
option leverage.

## Declared repair checks

A causal confirmation family was checked separately by calendar period:
next-bar follow-through, a break of the reclaim candle, two consecutive
follow-through closes, quarter-range and midpoint progress, EMA8 alignment,
three-candle directional structure, and a boundary retest. None maintained PF
1.5 with a positive median in 2024, 2025, and 2026. Fixed exits at 5, 10, 15,
20, 30, 45, 60, and 90 minutes also all failed that same cross-period gate.
Daily trend, prior-day compression, gap direction, and opening-range-size
context likewise failed to produce a repeatable three-period edge.

No filter is promoted from this audit. The original 21-trade option result is
now labeled `promising_inconsistent`, not a passed strategy. This evidence
correction does not alter the user's saved switch or the running entry rule.

## Production parity check

The paid one-minute data contains exactly 390 regular-session bars per full
day, from 09:30 through 15:59 ET. Production storage also contains sparse
extended-hours Alpaca bars. The extended-hours filter is therefore a required
data-boundary repair.

Replaying the six recent Failed-Range trigger days with and without those
extended-hours rows produced the same six trigger timestamps; the sparse rows
changed VWAP only slightly. The mismatch was real, but it did not cause those
six losses and must not be presented as the profitability fix.

Historical signal parity remains exact: 29 production candidates match the
paid research strategy on the frozen May–July SPY bar file.

## Next valid gate

The strategy should remain paper-only until either a predeclared replacement
passes multiple chronological periods with enough independent option fills,
or the user chooses to stop its order authority while research collection
continues. Research observation can continue regardless of that execution
choice.
