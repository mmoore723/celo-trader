# TSLA Two-Leg dynamic-exit study — September 9, 2026

## Outcome

Keep the current 90-minute paper/live exit. Preserve the strategy and continue
research; do not promote any dynamic exit from this family yet.

The armed 3-ATR trail was the only candidate to pass the earlier-data gate. It
did not pass the untouched later gate because only 9 outcomes were fully
comparable and their median return was negative. This is promising evidence,
not validation.

| Exit | Earlier results | Earlier PF | Earlier median | Earlier P&L | Earlier max drawdown | Later results | Later PF | Later median | Later P&L |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed 90m control | 64 | 1.9093 | 1.9208% | $2,643.80 | $1,044.60 | 9 | 4.5072 | 3.3664% | $1,075.30 |
| Structural stop | 64 | 0.8453 | -5.5285% | -$501.20 | $1,086.10 | 9 | 1.3777 | -3.6932% | $140.30 |
| Confirmed VWAP + EMA | 64 | 1.8108 | 0.1626% | $2,278.80 | $953.00 | 9 | 2.3924 | 0.1706% | $770.30 |
| Armed 3-ATR trail | 64 | 2.4009 | 1.7852% | $2,508.80 | $751.30 | 9 | 2.7876 | -0.9205% | $625.30 |
| Hybrid | 64 | 0.8465 | -4.0908% | -$401.20 | $968.40 | 9 | 0.0163 | -3.6932% | -$404.70 |

## Frozen protocol

- Source: the paid TSLA one-minute underlying archive and original exact-option
  Two-Leg report, August 1, 2025 through July 31, 2026.
- Entry universe: 76 of 127 original outcomes reproduced by the current
  production entry rule.
- Contract and entry: original option symbol, timestamp, and actual ask were
  held fixed for every exit.
- Exit: first real bid within five minutes after a completed-candle decision;
  no midpoint or synthetic option price.
- Costs: $0.65 per contract per side plus $0.01 adverse option-price slippage
  per side.
- Comparison: only the 73 signals with a real bid for all five exits.
- Split: dates before May 19, 2026 selected the candidate; dates on or after
  May 19 were untouched until that selection was made.
- Gate: at least 30 earlier and 10 later outcomes, PF at least 1.5, positive
  median and P&L, and maximum drawdown no worse than the fixed control.

## Integrity checks

All 76 fixed-control bids exactly matched the prior paid report. The one later
armed-trail outcome excluded from the common comparison had no new bid until 8
minutes 38 seconds after its decision. The execution window was not stretched
to force the ten-outcome gate. The dynamic rules never place orders and cannot
change paper or live exits.

The next exit family should be predeclared separately. This result rules out an
immediate structural stop and the tested hybrid; it does not rule out the
Two-Leg entry or every possible dynamic exit.
