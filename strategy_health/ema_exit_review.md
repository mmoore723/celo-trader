# EMA Pullback exit evidence — September 10, 2026

## Reproduced defect and scoped correction

The runtime strategy uses 15-minute bars. The frozen standalone runner uses
SimulationConfig(session_exit_time=15:55), but Simulator compares bar-start
timestamps. Its last regular bar starts at 15:45. A flat-position reproduction
therefore exits next day as end_of_data, not at the prior session close.
This affects replay interpretation; it does not establish a live-order loss.

The new observation protocol explicitly corrects session alignment: the final
15:45 bar is evaluated at its 16:00 close. Stop/target retain priority; neither
an incomplete 15-minute bar nor five-minute subsample may trigger early.
Entry's structural stop and 2.06R target remain frozen, and the 75-bar cap is
preserved. Earlier runner/timer results are NOT relabeled or rewritten.
The legacy research runner remains an audit artifact, not a valid reference
for intraday session exits. Reference tests explicitly select 15:45 there.

Source: research/engine/strategies/ema_pullback_rth.py, simulator.py,
research/jobs/run_ema_pullback_rth.py, run_ema_timeframe_study.py,
trading/tested_strategy_research.py and trading/loop/research_pass.py.
No executable strategy, risk setting, switch or broker route changes.

## External review before correction

Ten primary documentation sources checked September 10, 2026. These establish
timing/data semantics, not a profitable EMA parameter selection:

1. [TradingView strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/): bar-close calculation and next-tick execution are distinct; preserve causal observation rather than inventing an earlier fill.
2. [TradingView time](https://www.tradingview.com/pine-script-docs/concepts/time/): distinguish opening timestamp from closing timestamp.
3. [Alpaca aggregation FAQ](https://docs.alpaca.markets/us/docs/market-data-faq): minute labels identify the left boundary of the aggregation interval.
4. [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars): explicit timeframe and pagination; don't treat 15-minute data as five-minute bars.
5. [Tradier time and sales](https://docs.tradier.com/docs/timesale): supports 1/5/15-minute intervals with interval OHLCV; a candle is not an executable option bid.
6. [Databento schemas](https://databento.com/docs/knowledge-base): OHLCV timestamps mark interval starts; absent trades can mean absent records, not invented candles.
7. [NYSE trading hours](https://www.nyse.com/trade/hours-calendars): normal equity core session ends at 16:00; calendars also contain shortened sessions.
8. [QuantConnect time consolidators](https://www.quantconnect.com/docs/v2/writing-algorithms/consolidating-data/consolidator-types/time-period-consolidators): aggregation boundaries and alignment are explicit, not interchangeable across timeframes.
9. [Backtrader execution timing](https://www.backtrader.com/docu/cerebro/cheat-on-open/cheat-on-open/): prior-close decisions and next-open execution must not be conflated.
10. [Cboe session distinctions](https://www.cboe.com/document/tech-spec/document/technical-specifications/equity-options-extended-trading-hours-faq/): stock, ETF and extended option sessions differ. Never assume every option has a usable post-close price.

## Evidence and remaining limitations

Tests use genuine default 33/165/365 EMA signals, both directions, stop/target/
session paths, volume-preserving one-minute aggregation, and source/config/
timeframe/session proof. Synthetic tests prove implementation, not profitability.
Forty overlapping recorded plays remain independent, with shared quote reads,
restart safety and account/protocol isolation. Existing five-minute exits keep
their default behavior. The UI labels the corrected session policy explicitly.

Missing final bars or fresh same-contract option bids remain unmeasurable.
This normal-session protocol does not claim holiday/early-close support;
missing early-close bars cannot be fabricated into a 16:00 result.
The 365 completed 15-minute bars require more than 14 complete normal sessions.
Fresh admin history at 03:19 ET: META 294 complete bars, SPY 311, NVS 0.
Thus none could warm up using the previous collected-minute-only input.

EMA research.2 now reuses the five-minute history already fetched by the same
research pass. Aggregate three real, completed five-minute bars into 15-minute
bars; prefer complete collected bars on overlap. History may fill earlier gaps
but cannot replace or advance the newest collected signal candle. Missing,
duplicate, invalid and future constituents are excluded, never fabricated.
No new API calls or stored candle copies are added. No EMA length or risk
threshold is lowered. Other strategies' history remains unchanged. This input
policy is versioned and recorded on each EMA candidate so earlier samples
are not mixed with the newly supplied history. It is still limited by actual
provider coverage; do not claim every ticker has sufficient history until checked.
Next: diagnose real coverage and paired after-cost outcomes, then predeclare
dynamic-exit experiments with untouched later-date validation. No PF claim.
