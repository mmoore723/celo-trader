# Midday Breakdown exit tracking — September 10, 2026

`V2_MIDDAY_BREAKDOWN` is the default five-minute, short-only compact-base
breakdown strategy. Freeze the original base-high/ATR stop and 2R target.
There is no trailing stop. Its existing once-per-session signal rule is
unchanged; the collector itself has no cooldown or allocation limit and
tracks every recorded candidate independently.

Sources inspected: `research/engine/strategies/midday_breakdown.py`, imported
ATR/session/VWAP helpers, `research/engine/simulator.py`,
`research/jobs/run_midday_breakdown.py`, `trading/tested_strategy_research.py`.
The runner explicitly exits at the 15:55 bar and inherits a 75-bar cap.
For its entry window the session boundary occurs before that holding cap.

Skip entry-bar exits and evaluate only completed five-minute candles. Stop
wins same-bar ambiguity. A session decision is observed at 16:00, never
at the unfinished 15:55 candle's open. Reference tests exercise real default
strategy signals followed by target, stop and flat-to-session outcomes.

Save all four time settings as ISO strings with a source fingerprint so the
database round trip preserves proof. Bullish rows cannot belong to this
short-only source and are unmeasurable; no new entry gate is introduced.
Capture a fresh bid for the entry's exact option contract after the first
persisted decision. Use existing conservative costs; preserve missing prices
as missing. The 90-minute check remains a separate comparison.

Next: evaluate matched actual-exit losses before testing entry changes or a
dynamic exit. Repeated base-break setups versus the source's first-break-only
rule is a separate entry experiment, not a reason to silently mix versions.
Any tuning needs outside-source review and untouched later-date validation.
