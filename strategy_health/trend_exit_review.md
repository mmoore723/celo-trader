# Generic Trend Continuation exit — September 10, 2026

This is `V2_TREND_CONT`, not the separately reviewed SPY execution strategy
`V2_SPY_TREND_CONT`. No entry, exit, threshold, timer comparison or trading
setting changes. This release measures the original strategy's exit.

Sources inspected: `research/engine/strategies/trend_continuation.py`,
`research/engine/simulator.py`, `research/jobs/run_trend_continuation.py`,
and `trading/tested_strategy_research.py`.

The source fixes an entry-candle structural stop and 2R target. ATR helps
define the initial stop, but the stop does not trail. The simulator ignores
exit touches on the entry five-minute candle, checks subsequent candles,
chooses the stop if a candle reaches both levels, and otherwise closes at
75 managed bars or the 15:55 bar's close. Exit observation is at the completed
five-minute close, not an assumed intra-candle exact fill. The 75-bar cap is
observable at entry + 380 minutes; session close is observable at 16:00.

New candidates pin the source fingerprint/default configuration and retain
their original stop/target. Missing/mismatched proof is unmeasurable. Capture
the same option contract's fresh bid after the first persisted exit decision,
then apply the same conservative costs used by the timer comparison. Missing
prices remain missing; no historical outcomes are relabeled or fabricated.

Research may track overlapping entries independently; the simulator's
single-position allocation limit is not a research cooldown. Keep the existing
90-minute sample separate from actual-exit PF. Once prospective outcomes are
available, compare entry direction, option selection, and exit performance
before proposing dynamic exits or entry changes. The current losing timer
sample alone cannot establish which of those needs changing.
