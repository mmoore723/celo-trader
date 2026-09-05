# VWAP 10:30 Displacement 90-minute parity audit

## Result

The PF 6.73 shown in Settings did not describe the paper rule that the bot is
currently allowed to execute. It came from five TSLA contracts closed by a
structural VWAP/high-of-day exit. The user-approved paper version instead
holds the same selected contract for 90 minutes.

Repricing the frozen TSLA and AMZN entries at the first real same-contract bid
in the 90-minute exit window produced five measurable outcomes:

| Ticker | Signal date | Entry ask | 90-minute bid | One-contract P&L after costs |
| --- | --- | ---: | ---: | ---: |
| TSLA | 2025-09-24 | $2.13 | $2.39 | +$23.76 |
| TSLA | 2025-10-17 | $1.93 | $1.17 | -$78.24 |
| TSLA | 2025-10-31 | $1.95 | $1.59 | -$38.24 |
| TSLA | 2026-02-24 | $1.93 | $2.90 | +$94.76 |
| AMZN | 2026-03-04 | $1.84 | $2.23 | +$36.76 |

The combined result is 3 wins, 2 losses, +$38.80, and PF **1.3331** after
$0.01 adverse option-price slippage per side and $0.12 per contract per side.
One additional TSLA entry on July 16 had no executable bid in the exact
90-minute window and is reported as missing instead of being priced at zero or
invented.

## Decision

Keep the user-approved paper switch and TSLA/AMZN scope unchanged so the bot
can collect prospective evidence. Replace the Settings PF with the exact
paper-policy PF 1.33 and make clear that it is below the 1.50 goal and based on
only five measured exits. Do not promote the strategy live from this sample.

The generalized fixed-hold repricer now accepts an explicit dotted rows path,
so future exit parity checks can reuse the exact signal, contract, entry time,
and ask without rerunning strategy or contract selection.
