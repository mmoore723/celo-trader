# Failed-Range runner protection — September 10, 2026, before session

Research-only protocol `recovery_vwap_then_option_3spread_2spread_30m_v1`.
Same v2.1.0 entry, contract and recorded ask as its paired30-minute control.
No immediate sale on reaching VWAP. No trading settings or native exits change.

The experiment adds one gate to the already-frozen option-profit policy:
after the entry minute, a full one-minute candle must close at or beyond the
entry-time VWAP recovery target, in the original signal direction. Freeze
that target and direction from candidate metadata. Do not recalculate VWAP
using later prices or count pre-entry/unfinished candles and wicks.

Persist both candle-close time and actual discovery time. Only a fresh
exchange bid AFTER discovery can arm the option trail. Pre-target option
peaks cannot arm it retroactively. Once armed, it uses the same3-entry-spread
gain threshold beyond costs and2-spread trailing distance as SPY Trend.
Both are long options; puts also benefit from premium rising. Never loosen
the trail; price only a subsequent exchange bid after the exit decision.
Both keep the30-minute cap. An unreached target leaves the timer unchanged.

Missing/invalid candles and gaps greater than120seconds remain missing
evidence. Late discovery of an old target cannot create a made-up timely
runner. The independent control can still be measured. Freeze errors affect
the test arm, not native trading. Quotes/candles are shared by contract/ticker
per checkpoint across all overlapping research plays; no portfolio cooldown.
Keep one compact durable row per candidate. Once target is known, stop
fetching candles for that candidate; after the trail finishes, quote again
only when its control is due. Old SPY Trend state and protocol remain intact.

## Why test this, rather than simply sell at target?

Two already-inspected current-version paper examples had complete29/29
post-entry minute candles. First full-close target exit modeled+$10.70 each.
Matched30-minute controls were+$30.70 and-$1.30. Immediate target selling
therefore cut the winner more than it helped the weak trade: net-$8 combined
per contract. Those are development receipt-time diagnostics, not untouched
results. They motivate a runner hypothesis, not selected winning thresholds.

No new thresholds were optimized here. September14–25 remains reserved for
later-date comparison, using identical paired plays, costs and result days.
The acceptance criteria and data limitations in option_profit_protection_review.md
apply: insufficient evidence is inconclusive; no automatic promotion. Shared
research contract selection is not the native paper7–21DTE profile, so report
those separately. Current tests cannot promise future PF1.5 or account growth.

The original frozen target comes from the reviewed implementation
strategies.spy_failed_range_recovery_v2. External mechanics reviewed for this
experiment family include [Alpaca trailing orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca),
[Fidelity order types](https://www.fidelity.com/trading/faqs-order-types),
[QuantConnect fill models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/equity-model),
and [backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
None establishes profitability for this particular rule.

Deployment uses the existing additive evidence table without historical
rewrites. Roll back the application release if health fails or research
interrupts scanning; retain the evidence table. Verify fresh production
matrix protocol, account separation, public bundle and warning logs.
