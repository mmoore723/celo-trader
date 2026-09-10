# Option profit protection — frozen September 10, 2026, before session

Research only for newly stamped SPY Trend v2.1.0 plays on every collected
ticker. No change to native 30-minute execution or user settings. Existing
entry quote/contract selection is shared by both arms; this is an exit-only
comparison using the research contract profile, not a claim about paper fills.

Arm after bid exceeds entry ask by $0.033 modeled round-trip costs plus three
entry spreads. Follow two spreads behind the best sampled bid, using the
larger of current and entry spread (minimum $0.01). Never loosen a stop.
Both puts and calls are long premiums. Test the prior stop before tightening.
Trigger time is receipt time. Sell valuation requires a subsequent exchange
bid within 60 seconds, not the quote that triggered the decision. Both arms
retain the priced-entry +30-minute cap; require that cap by 3:55 PM ET.

Exchange bid AND ask must be fresh within 60 seconds for spread decisions.
Repeated exchange bids cannot extend path coverage. A gap over 120 seconds
makes the trail unmeasurable; its independently priced control remains.
Checkpoints run on the order-free worker before/among ticker scans, at most
once per 30 seconds within a pass. This is quote polling, NOT a strategy
cooldown. Slow broker calls can still create gaps; disclose them, don't fill
them in. One quote per contract per checkpoint serves every overlapping play.
One compact state row per candidate persists across restarts; no tick archive.

Only exact paired outcomes enter the comparison. One contract, $0.65/side,
$0.01/side friction, buy at recorded entry ask, sell at later bid. Recorded
entry snapshots are modeled prices, not guaranteed fills; no exchange entry
timestamp exists in the legacy candidate quote table. Cross-ticker research
contract selection differs from native paper selection. No automatic promotion.

These multiples are a first economic-cost/spread hypothesis, not optimized
to make inspected September 8/9 trades win. Dates through September 9 are
development. Reserve September 14–25 for later-date validation; insufficient
matched/day coverage stays inconclusive. Target 30 matched plays over 10 days,
PF >=1.5 after costs, positive typical result, paired mean improvement,
no worse drawdown and day-cluster uncertainty checks before recommending.
Those criteria are research review requirements, not account setting changes.

Mechanics draw on previously reviewed primary sources: [Alpaca trailing
orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca), [Fidelity order
types](https://www.fidelity.com/trading/faqs-order-types), [QuantConnect
fill models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/equity-model),
and [backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
These sources motivate causal pricing and separate validation; they do not
establish profitability of these particular thresholds.

Release: additive table only, no rewrites of historic measurements. Rollback
application commit if health fails or the observer interrupts signal scanning;
leave the additive evidence table intact. Missing quotes are data-quality
findings, not a reason to weaken timing requirements or claim profitability.
