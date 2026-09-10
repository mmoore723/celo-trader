# Afternoon Reversal exit tracking — September 10, 2026

Scope: `V2_AFTERNOON_REVERSAL`. No entry, exit or threshold changes; no orders.
The current runtime constructs the default strategy on completed five-minute
bars. Its initial stop is based on confirmed swing structure and ATR, and its
target is 2R. There is no trailing-stop method or VWAP-cross exit.

Sources inspected: `research/engine/strategies/afternoon_reversal.py`,
the ATR/session/VWAP helpers it imports, `research/engine/simulator.py`,
`research/jobs/run_afternoon_reversal.py`, `trading/tested_strategy_research.py`.
The historical runner explicitly sets the 15:55 bar session exit and inherits
the simulator's 75-bar cap. The session ends first for afternoon entries.

Reference tests preserve next-bar entry, skip entry-bar exits, choose the
stop on ambiguous bars and compare completed-bar exit decisions. The last
session candle becomes observable at 16:00, not at its 15:55 open. Capture
a fresh same-contract option bid after the first persisted decision; never
substitute the underlying stop price for an executable option fill.

The proof stores configuration time values as ISO strings so serialization
cannot silently invalidate every candidate. Source/configuration mismatches,
missing bars and missing quotes remain explicit unmeasurable evidence.
All overlapping plays are tracked without allocation limits or cooldowns.
The original 90-minute comparison stays separate from actual-exit results.

Next: use paired after-cost results to distinguish entry-direction errors,
option selection costs and exit giveback. Do not infer that a dynamic exit
will help before measuring those causes. Rule tuning requires a separate
outside-source review and an untouched later-date sample.
