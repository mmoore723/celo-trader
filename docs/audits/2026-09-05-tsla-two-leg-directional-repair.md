# TSLA Two-Leg directional-confirmation repair

Date: September 5, 2026

## Outcome

The current TSLA Two-Leg entry was too permissive. It accepted a completed
one-minute reclaim even when that reclaim candle did not show meaningful
same-direction buying or selling pressure. Version 2.1.0 requires the reclaim
candle to have at least one causal same-direction feature: momentum, engulfing,
or rejection. The 90-minute exit and the user's saved switch are unchanged.

This is a paper repair, not a claim that future profit is guaranteed. The
later-period figures were already visible when the repair was selected, so the
repaired rule still needs fresh forward results before live authority.

## Inputs and execution model

- Underlying bars: paid TSLA one-minute data, August 1, 2025 through July 31,
  2026; SHA256
  `eeae427d707adc321538eb6f102cf513644723936e9d1f88d5549eca10e604ac`.
- Saved option outcomes: `paid_tsla_two_leg_tuning_v1.json`; SHA256
  `b7eb48398820a8e2d4427e68395ed057166da1731cad603308f7deaa36414f4a`.
- Fill model: actual next-minute option ask at entry and actual same-contract
  bid 90 minutes later.
- Costs: $0.01 adverse option-price slippage and $0.65 commission per contract
  on each side.
- Chronological split: May 19, 2026. No later candle was used to approve an
  earlier entry.

The exact production state machine matched all 127 saved baseline signal times
and directions before the new confirmation was applied. The deterministic
repair audit then reproduced 76 accepted outcomes and zero accepted-row timing
or direction mismatches.

## Results after costs

| Period | Trades | Wins | PF | Net P&L, one contract | Median return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Older | 66 | 36 | 1.8237 | $2,507.20 | 1.6972% |
| Later | 10 | 7 | 3.9494 | $1,032.00 | 3.1889% |
| All | 76 | 43 | 2.0428 | $3,539.20 | 1.9208% |

The unrepaired 127-trade baseline was PF 1.4919 after the same costs. The repair
removes 51 weak-reclaim entries while retaining nearly all of the baseline net
P&L.

## Current-paper stress check

The unfiltered current sample has seven usable independent TSLA episodes: PF
0.9274, net -$23.10, and a negative median. The three episodes actually entered
by the bot were worse: PF 0.0116 and net -$144.90.

Scanner candles remain available for five of the seven episodes. The repaired
rule keeps the August 24 and August 26 wins, rejects the August 25 loss and the
August 27 near-flat win, and retains the September 1 loss. That reconstructable
subset becomes PF 4.0027 and net +$220.10. This is exploratory evidence because
the outcomes were known before the repair; the two older episodes are not
invented or silently classified.

## Alternatives rejected

- Raising the initial impulse threshold from 1.0 through 2.0 ATR did not remove
  any of the five reconstructable current TSLA signals.
- A 60-minute exit alone fell below the PF 1.5 gate in older data after current
  costs: PF 1.2895 for the baseline and 1.4551 with a 1.5-ATR impulse.
- The previously tested contract-selection challenger failed its declared
  coverage/holdout gate, so the reviewed nearest-expiry policy remains.
- Multi-timeframe alignment failed later data; option-pressure confirmation had
  only 7 older and 1 later outcome and only about 6% coverage.

## Reproduction

Run:

```bash
python research/jobs/audit_tsla_two_leg_directional_repair.py \
  --input /path/to/paid_tsla_two_leg_tuning_v1.json \
  --bars /path/to/paid_tsla_2025_08_01_to_2026_07_31_1m.csv
```

The command exits nonzero if the frozen bar hash, accepted counts, wins, or
period profit factors no longer reproduce.
