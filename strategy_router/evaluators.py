"""
strategy_router/evaluators.py — Active strategy evaluator table.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Extracted 2026-07-17 so strategy_health/engine.py can call the exact same
raw evaluate() functions the live router uses, instead of hand-duplicating
this list and risking drift if a strategy is added/removed/disabled here.
NOTE: BOS_MSS intentionally absent — its sweep detection was merged into
FVG as a confidence modifier (running both double-voted the same move).
"""

from strategies import (
    inst_orb, bos_mss, vwap_pb, fvg, ifvg, mid_brk, aft_rev, trend_cont,
    chan_break, gap_go, liquidity_sweep, orb_pullback_v2, trend_continuation_v2,
    spy_trend_continuation_v2, spy_afternoon_fvg_v2, spy_afternoon_reversal_v2,
)

# ── Active evaluator table (single source of truth) ───────────────────────────
ACTIVE_STRATEGIES = [
    ("INST_ORB",   inst_orb.evaluate),
    ("VWAP_PB",    vwap_pb.evaluate),
    ("FVG",        fvg.evaluate),
    ("IFVG",       ifvg.evaluate),
    ("MID_BRK",    mid_brk.evaluate),
    ("AFT_REV",    aft_rev.evaluate),
    ("TREND_CONT", trend_cont.evaluate),
    ("GAP_GO",     gap_go.evaluate),   # 2026-07-23, Gap 2 — see strategies/gap_go.py.
                                       # Present here (so backtester/audit tools CAN
                                       # exercise it). ON by default 2026-07-31 per
                                       # explicit user decision — still has zero
                                       # backtest history of its own.
    ("LIQ_SWEEP",  liquidity_sweep.evaluate),  # 2026-07-31 — see strategies/liquidity_sweep.py.
    ("V2_ORB_PULLBACK", orb_pullback_v2.evaluate),
    ("V2_TREND_CONT", trend_continuation_v2.evaluate),
    ("V2_SPY_TREND_CONT", spy_trend_continuation_v2.evaluate),
    ("V2_SPY_AFTERNOON_FVG", spy_afternoon_fvg_v2.evaluate),
    ("V2_SPY_AFTERNOON_REVERSAL", spy_afternoon_reversal_v2.evaluate),
                                       # Fades a swept swing high/low. ON by default per
                                       # explicit user decision — zero backtest history.
    # ("CHAN_BREAK", chan_break.evaluate),  # disabled — 0% WR in backtests, needs fix
]
