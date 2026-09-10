# Afternoon Compression Breakout: exit measurement

Reviewed September 10, 2026. Observation only; no order routes or entry rules changed.

The deployed factory uses the wider-baseline configuration: 0.004 maximum
compression and entry through 15:00, not the class defaults 0.0025 and 14:30.
The range is frozen from 12:30–13:14 one-minute bars (minimum 30).
The completed breakout must agree with VWAP and EMA(9/20). Long stop is the
lower of box low and close minus ATR; short reverses that. Target is 2R.
Source once-per-session emission remains unchanged, not a collector cooldown.

Original paid research under /Applications/celo_trader/research/jobs:
- assess_paid_spy_afternoon_compression_breakout.py: fixed 30-minute default.
- tune_paid_spy_afternoon_compression.py: same timer for entry comparisons.
- screen_cross_ticker_afternoon_compression.py: wider-baseline, fixed timer.
- tune_paid_spy_afternoon_compression_exits.py: separate 30/60-minute,
  structural-stop and confirmed VWAP/EMA experiments. It does not validate
  the source's 2R target or automatically promote any dynamic exit.

New protocol observes source stop/target on completed one-minute candles.
It skips the entry minute because its high/low may precede the option quote.
Entry ask must be inside that minute; a later ask cannot price an earlier exit.
Stop wins ambiguous OHLC; first decision persists across restarts. Only a
fresh same-contract bid after that decision can price the exit, with costs.
Missing candles or quotes are unmeasurable, never invented fills or zero losses.
The explicit normal-session fallback is 16:00, not a supposedly authored
75-bar timer. Source itself supplies no timed exit. Existing timed samples
remain separate. Early-close sessions need calendar-aware work; no fabricated
16:00 evidence when their bars are absent. Timing references are recorded in
ema_exit_review.md; this is measurement, not a new executable trading rule.

Acceptance: genuine long/short source signals through the runtime adapter;
reference stop/target/session exits; one-minute causal boundaries; invalid
proof/late ask/missing data; 40 overlapping plays and account isolation;
matrix separation from 30-minute results. No profitable-performance claim.

Next comparison: all-opportunity source variant separately versioned; paired
fixed 30-minute versus original stop/target versus predeclared dynamic exits,
using identical entries and real option costs, with untouched later dates.
Do not write this strategy off based on timer results or loosen every gate.
