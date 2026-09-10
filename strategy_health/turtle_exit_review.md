# Turtle Soup Reversal exit evidence — September 10, 2026

Scope: `V2_TURTLE_SOUP_RTH`, default completed-five-minute runtime rules.
Keep the original sweep-extreme stop and fixed 1.5R target. The pending
sweep/next-bar confirmation state controls entry only; it clears when a signal
appears. A later sweep must not overwrite the recorded entry's exit levels.

Sources inspected: `research/engine/strategies/turtle_soup_rth.py`,
`research/engine/simulator.py`, `research/jobs/run_turtle_soup_rth.py`,
`research/jobs/run_paid_databento_job.py`, `trading/tested_strategy_research.py`.
The standalone runner explicitly selects the 15:55 session candle and inherits
the 75-bar cap. There is no trailing exit method.

Parity tests exercise genuine one-sided long and short sweeps, then stops,
targets or a flat-to-session path. A two-sided sweep picks downside first in
the current source; preserve and test that priority rather than silently
changing it. The initial mirrored fixture swept both sides and failed intended
direction coverage; fixing that fixture restored independent long/short tests.

Freeze source/configuration proof with ISO entry-window times. Skip the entry
candle, inspect completed five-minute bars, stop wins same-bar ambiguity and
the final session decision is observable at 16:00. Use a fresh same-contract
option bid after the first persisted decision and existing conservative costs.
Target outcomes use the explicit 1.5R reason. Missing proof/bars/quotes remain
unmeasurable; never relabel historical timer marks as original exit results.

Track all recorded overlapping candidates without allocation limits. Source
entry rules, paper/live settings and historical evidence are unchanged. Next,
compare matched exit outcomes and profit giveback before designing a dynamic
exit or a separate two-sided-sweep experiment. Any rule tuning requires
outside-source review and untouched later-date validation.
