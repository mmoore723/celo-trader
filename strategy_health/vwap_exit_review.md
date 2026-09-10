# VWAP Pullback exit evidence — September 10, 2026

Scope: generic `V2_VWAP_PULLBACK`, not the 10:30 Displacement or KER strategies.
Its runtime defaults define a VWAP touch/reclaim or rejection, an initial
structural/ATR stop and a 2R target. VWAP is an entry feature, not an exit
trigger. The source has no trailing-stop method. No entry rules are changed.

Inspected sources: `research/engine/strategies/vwap_pullback.py`, its imported
ATR/EMA helpers, `research/engine/simulator.py`, `research/jobs/run_vwap_pullback.py`,
and `trading/tested_strategy_research.py`. The standalone walk-forward command
does not configure a session exit. This observer explicitly uses an intraday
boundary (the 15:55 candle completed at 16:00); it does not claim parity with
overnight holds from that standalone command. The protocol includes `rth`.
Reference tests use the original simulator with that same stated boundary.

Preserve initial stop/target, skip the entry candle, inspect completed five-minute
candles, choose the stop when both levels touch, and retain the simulator's
75-bar holding cap. A decision is observable at candle close, never its open.
No source changes, parameter search, or profitability claims accompany this
measurement repair. The 90-minute check remains a separate comparison.

New candidates save their exact source/configuration proof and original levels.
After the first exit decision is persisted, capture a fresh bid for the same
option contract. Missing or stale quotes stay unmeasurable. Apply the existing
spread/slippage/commission assumptions; do not manufacture prior exits.
Every overlapping candidate is tracked, without a research allocation cap.

Next analysis: compare actual exits against the 90-minute check on matched
entries. Separate wrong-direction setups, option-price/spread costs and profit
giveback before proposing dynamic exits. Any parameter change requires its
own outside-source review and untouched later-date validation.
