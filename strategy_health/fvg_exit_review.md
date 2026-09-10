# Generic Fair Value Gap exit evidence — September 10, 2026

Scope: `V2_FAIR_VALUE_GAP`, not `V2_SPY_AFTERNOON_FVG`. Current runtime uses
the default five-minute first-retest strategy. Its stop is the more distant
of the retest extreme and one ATR; its target is 2R. No trailing-stop method
exists. No entry gates, thresholds, execution routes or switches are changed.

Sources inspected: `research/engine/strategies/fair_value_gap.py`, imported
ATR/EMA/session/VWAP helpers, `research/engine/simulator.py`,
`research/jobs/run_fair_value_gap.py`, `trading/tested_strategy_research.py`.
The standalone runner does not set a session exit. This prospective protocol
explicitly names its RTH boundary, unlike an overnight historical hold. Its
reference simulator uses the same 15:55 bar boundary and default 75-bar cap.
This is not a claim that overnight outcomes and intraday outcomes are equal.

Freeze the entry's original stop/target and source/configuration proof.
Skip the entry candle; inspect completed five-minute bars; stop wins when
both levels touch. Decisions become observable at bar close, including 16:00
for the last regular-session candle. Capture a fresh same-contract bid after
the first persisted decision and apply the existing option-cost assumptions.
Missing proof, bars or quotes never become a made-up priced outcome.

The 90-minute check remains separate. Track all overlapping candidates without
a research cooldown. After matched actual exits exist, compare entry direction,
spread/option selection, and profit giveback before considering dynamic exits.
Rule changes require separate outside-source review and untouched later dates.
