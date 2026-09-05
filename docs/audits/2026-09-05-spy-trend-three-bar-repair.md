# SPY Trend Continuation three-bar repair

## Decision

Keep SPY Trend Continuation enabled in paper mode. Replace the deployed
0.50-ATR room gate with a causal three-bar structure gate:

- A call requires higher lows across the last three completed bars.
- A put requires lower highs across the last three completed bars.
- The research observer still records every candidate before this order gate.
- A reviewed paper entry may not fill above the Tradier ask used by the study.

The strategy is not approved for live trading. The repair meets the research
PF target, but the same-broker filled sample is still too small.

## Why the prior repair was removed

The paid source report contained 156 option markouts. Reconstructing the exact
production adapter reduced that to 86 signals, and the existing 1:45–3:00 PM
SPY slot reservation reduced it to 72 order-reachable outcomes. On those exact
72 outcomes, the 0.50-ATR room rule retained 51 trades and produced:

- PF 0.5274 after modeled costs
- -$614.24 at one contract
- May PF 0.2425, June PF 0.3468, and July PF 1.2564

The deployed rule therefore contradicted its earlier notes and is superseded.

## Historical repair result

The three-bar definition already existed in the finite price-action variant
library before this repair. It uses completed bars only; it does not read a
future candle. Applied to the exact 72 order-reachable outcomes, it retained
46 trades:

| Period | Trades | Raw quote wins | Wins after costs | Net after costs | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| May 12–31 | 9 | 4 | 4 | +$117.84 | 2.3831 |
| June | 18 | 12 | 11 | +$176.68 | 1.5935 |
| July | 19 | 12 | 10 | +$137.44 | 1.7042 |
| All | 46 | 28 | 25 | +$431.96 | 1.7473 |

Each row uses one contract, the historical Tradier/OPRA ask at entry, the same
contract's bid 30 minutes later, $0.01 adverse option-price slippage on each
side, and $0.12 per contract on each side.

The prior manifest called every positive raw ask-to-bid move a win while its
PF and P&L included slippage and fees. The table now distinguishes those raw
quote wins from trades that remain positive after the stated costs.

This is a chronological consistency check, not a declared holdout pass. The
variant family was predeclared, but this exact repair was selected after all
three periods were visible. It is classified as promising and underpowered.

## Independent production evidence

On saved real-time Tradier observations, the same gate retained 21 SPY Trend
episodes across 12 days: 16 wins, +$784.96 after the same modeled costs, and PF
18.7593. Those are real quotes, not fills.

Only four linked Alpaca paper trades had the required causal metadata. The
qualifying subset had three wins, +$40, and PF 2.1111. Four fills are not enough
to promote a strategy.

## Execution defect found during the audit

The bot sized risk with a five-percent price allowance and also gave that
allowance to the Alpaca paper order as its fill ceiling. That allowed a reviewed
order to chase above the Tradier ask used to measure the strategy. The repaired
path still uses the allowance for risk sizing, but caps the order at the exact
analyzed ask. An unfilled order is more honest than recording a materially
different entry as evidence for the reviewed rule.

## Promotion boundary

This repair supports continued paper trading, not a profitability guarantee.
Live promotion still requires a larger independent cohort of same-broker order
fills with PF above the target after real slippage, commissions, rejections,
and missed fills.
