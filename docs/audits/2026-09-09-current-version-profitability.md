# Current-version profitability audit

## Finding

Research Results was combining prospective outcomes emitted by older strategy
code with the current repaired strategy versions. That made the current rules
appear to own losses they did not generate. No rows were deleted; the result
cohorts are now partitioned by the exact `strategy_version` recorded with each
candidate.

## Current forward evidence as of September 9, 2026

| Strategy + ticker | Current version | Fresh outcomes | Finding |
| --- | ---: | ---: | --- |
| SPY Afternoon Fair Value Gap | 2.1.0 | 0 | Not yet judgeable |
| TSLA Two-Leg Trend Pullback | 2.1.0 | 0 | Not yet judgeable |
| SPY Failed-Range Recovery | 2.1.0 | 1 | One win, about +$45.70 after configured costs; far too small to establish an edge |

The Failed-Range result used the saved Tradier ask of $3.34, the 30-minute bid
of $3.82, $0.01 adverse slippage on each side, and $0.65 commission on each
side: `(3.81 - 3.35) * 100 - 1.30 = $45.70`.

## Repaired historical evidence

| Strategy + ticker | Paid-option outcomes | PF | Chronological check |
| --- | ---: | ---: | --- |
| SPY Afternoon Fair Value Gap 2.1.0 | 19 | 2.22 | Training PF 1.89; holdout PF 4.72 |
| TSLA Two-Leg Trend Pullback 2.1.0 | 76 | 2.04 | Older PF 1.82; later PF 3.95 |

These historical repairs clear the numeric PF 1.5 goal, but they are not a
substitute for fresh same-version paper evidence.

SPY Failed-Range Recovery does not have a supported profitability claim. Its
small original paid-option slice had PF 3.04 over 21 outcomes, but the frozen
383-episode underlying audit failed stability in 2024, 2025, and 2026. Nine
causal confirmation variants and fixed holds from 5 through 90 minutes produced
no cross-period pass. It should continue collecting exact-version evidence; a
future replacement must be a distinct predeclared entry family rather than an
after-the-fact tweak to the losing observations.

## Product behavior

The Research page now labels paid-option evidence with its explicit cutoff date
and the live prospective cohort as `Current`. Earlier-version rows are preserved
and counted separately under the expanded proof details. Strategy switches,
broker mode, ticker scope, sizing, and order authority are unchanged.
