# Confirmed Opening-Range Breakout exits — September 10, 2026

Scope: `V2_ORB_CONFIRMED_BREAKOUT`, not the separate tradable ORB Pullback,
context-filtered ORB or RSI/MACD strategy. No entry rules or trading changes.
Default source uses the opening range's midpoint stop and a 1.5R target,
fixed when the confirmed breakout signal appears. No trailing method exists.

Sources inspected: `research/engine/strategies/opening_range_breakout.py`,
`research/engine/strategies/vwap_pullback.py` (`_session` helper),
`research/engine/simulator.py`, `research/jobs/run_opening_range_breakout.py`,
`trading/tested_strategy_research.py`. The runner sets a 15:55 candle session
exit and inherits the simulator's 75-bar cap. Source/configuration proof pins
the entry deadline as an ISO time string across database serialization.

Reference tests use both directions and stop, target, session paths. Ignore
entry-candle exits, decide only from completed five-minute candles, and choose
the stop on same-bar ambiguity. Session decision is observable at 16:00.
The shared structural observer compares original price levels; remap its
legacy target reason to 1.5R only for this protocol. Capture accepts that
reason as a genuine exit and the UI reports the correct ratio.

Latch the first decision before fetching a fresh same-contract option bid;
apply existing conservative costs. Preserve missing quotes/proof as missing,
keep the 90-minute check separate, and track all recorded overlapping plays.
The original once-per-session setup rule is unchanged, not a new allocation
cooldown. Source-rule experiments must remain separately identified.

Next: compare actual and timer exits on matched entries before deciding which
entry, contract or dynamic-exit experiment addresses measured losses. Any
rule tuning requires outside-source review and untouched later-date validation.
