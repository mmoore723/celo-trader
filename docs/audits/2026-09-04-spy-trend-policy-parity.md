# SPY Trend production-policy parity audit — 2026-09-04

## Result

The prior `V2_SPY_TREND_CONT` evidence was not an exact replay of the rule the
bot can execute. Its raw trend calculation matched production, but the saved
option report included repeated breakouts that the live adapter suppresses.
It also did not apply the portfolio rule that reserves the SPY slot for
Afternoon FVG from 1:45 through 3:00 PM ET.

The historical “passed” label is therefore revoked. The strategy remains
available in paper mode, but it is not eligible for live orders.

## Reconciliation

All comparisons used the frozen paid SPY minute archive with SHA-256
`a9cfcb0d273881b7831d67b9321653350571b16cce17aed1b83f37c66d748273`.

| Cohort | Option outcomes |
| --- | ---: |
| Original one-position report | 156 |
| Reachable after production breakout suppression | 86 |
| Reachable after suppression and the deployed slot reservation | 72 |
| Original outcomes not emittable by production | 70 |

The exact deployed-policy replay used real option ask at entry and the same
contract's real bid after 30 minutes. Account results include production
growth sizing, $0.01 adverse slippage per side, $0.12 per contract per side,
and $10 per active data month.

| Period | Trades | Wins | PF | Net after costs | Median return |
| --- | ---: | ---: | ---: | ---: | ---: |
| May selection | 18 | 7 | 0.5973 | -$318.64 | -2.2783% |
| June validation | 25 | 14 | 0.8048 | -$213.08 | 0.3420% |
| July holdout | 29 | 13 | 1.3580 | +$128.56 | -0.2485% |
| All periods | 72 | 34 | 0.9823 | -$43.88 | -0.0558% |

A $5,000 replay ended at $4,956.12 with a 17.4566% maximum drawdown. No
period passed the full launch gate of PF at least 1.50, positive net profit,
positive median trade, and an adequate independent sample.

## Guard added

The reviewed evidence now records and hashes the separate portfolio-policy
source that changes which entries are reachable. Catalog integrity fails
closed if that policy changes without a refreshed audit. A regression test
also locks the 72-outcome production cohort and failed evidence grade so the
old 156-trade PF cannot silently return to Settings.
