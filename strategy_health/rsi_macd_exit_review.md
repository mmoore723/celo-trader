# ORB RSI/MACD Short exit evidence — September 10, 2026

Source: research/engine/strategies/orb_rsi_macd.py, _ema/_rsi helpers,
_session, research/engine/simulator.py, research/jobs/run_paid_databento_job.py,
research/engine/option_markouts.py and trading/tested_strategy_research.py.

The source emits bearish setups only: narrow opening range, a buffered break
below its low, price below VWAP, RSI below 45 and fast EMA below slow EMA.
The stop is the opening-range midpoint; target is 1.5 times initial risk.
Those frozen exit prices must not move with later opening ranges or indicators.
The original entry engine permits at most one signal per ticker/day. It also
needs prior regular-session history for its 26-bar slow EMA; four opening
bars alone cannot initialize it. Neither restriction is changed here.

The paid runner passes active_date to restrict warmup signals, but its option
markout function uses explicit hold_minutes (CLI default 60), not these
structural exits. Current runtime's 90-minute check is also a timer comparison.
Do not relabel either timer evidence as this stop/target protocol.

This separately identified intraday observation retains the shared simulator's
75-bar cap and explicitly stops at the completed 15:55 candle (16:00). That
RTH ceiling is a measurement policy, not an authored timer in the paid runner.
The completed-bar timing and executable-quote distinctions follow the ten
primary-documentation review in ema_exit_review.md; no parameter optimization
or change to paper/live exit behavior is performed.

Tests cover a real bearish default signal with prior history, stops, targets,
flat-to-session paths, source midpoint/target metadata, causal bar completion,
entry-candle exclusion, stop-first ambiguity, proof/direction rejection, forty
overlapping plays, restart behavior, and account/protocol isolation. Active-date
proof serializes explicitly; nondefault evidence is not accepted accidentally.
Synthetic tests establish fidelity, not profitability. Fresh same-contract
option bids and conservative costs remain required; missing data is not profit.

Next: compare matched structural and timer exits, measure entry rejections and
the once-per-day restriction, then predeclare all-opportunity/dynamic-exit
variants with outside-source review and untouched later dates. Retain the
separate NVS minute-coverage issue. No execution switches or risk limits change.
