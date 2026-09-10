# Range Sweep Reclaim (Calls): exit measurement

Reviewed September 10, 2026. No entry rules, thresholds, or order settings changed.

Runtime uses range_bars=30, maximum_efficiency=.30, minimum_sweep_atr=.15;
class defaults differ. Only calls pass the runtime adapter. A quiet-range low
is swept, then a completed bullish minute reclaims it below VWAP. The stop is
the lower sweep/reclaim low minus .25 ATR; target is that entry's session VWAP.
Minimum VWAP room and reward/risk remain unchanged. Source rearming is a
price-based setup definition, not a collector allocation cooldown. It remains
explicit for a separately versioned all-opportunity comparison.

The original compare_paid_spy_range_sweep_long_exits.py in the local research
workspace compares 30-minute holding against moving-VWAP touch/close exits
with a 60-minute cap. Those are distinct hypotheses; they do not validate the
frozen entry target. Do not call the frozen target 2R or silently move it later.

This collector uses the original frozen stop/target and an explicit 16:00
normal-session fallback, with no invented 75-bar hold timer. Skip entry minute;
ask must arrive inside that minute. Decisions occur at completed minute close.
Stop wins ambiguity. Price only the first decision using a fresh real bid on
the same option contract, after costs. Missing data stays unmeasurable.
Timing references are recorded in ema_exit_review.md. Early-close calendar
support remains a separate limitation, not fabricated end-of-day prices.

Tests cover genuine runtime call signals, simulator stop/target/session paths,
frozen target despite later volume changes, causal minute boundaries, invalid
proof/direction/late ask/missing bars, 40 overlapping observations, account
isolation/restart, and separate 30-minute versus actual-exit matrix evidence.

Next: compare fixed 30-minute, frozen entry VWAP, and predeclared moving-VWAP
exits on identical entries with executable costs and untouched later dates.
Collector implementation is not a profitability or promotion claim.
