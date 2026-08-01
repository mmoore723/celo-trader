"""
playbook_examples/rvol_gates.py — Real (not stale-docstring) RVOL gate
values, re-derived the same way strategy_router.py's own eval functions
compute them.

Split out of the old single playbook_examples.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

NOTE: this module imports `_get_dynamic_rvol_threshold` and
`MarketStructureAnalyzer` from strategy_router.py. As of this split,
strategy_router.py does not actually export `_eval_inst_orb` (a pre-existing
bug, confirmed unrelated to this refactor — see the config.py split commit
for the same finding), which breaks importing this whole package today.
That bug lives in strategy_router.py/playbook_examples' evaluator wiring,
not in this file, and is out of scope for a pure file-size split — flagging
it here again since this module is one of the ones affected.
"""

import numpy as np
import pandas as pd

from strategy_router import _get_dynamic_rvol_threshold, MarketStructureAnalyzer

# Fixed (non-dynamic) RVOL gates for the 4 strategies that don't call
# _get_dynamic_rvol_threshold() at all — read directly off the literal
# comparisons in strategy_router.py (`rvol >= 1.5`, `c_rvol < 1.5`, etc.),
# not off docstrings, which have drifted from the real code more than once
# this session. AFT_REV has NO RVOL floor (gates on raw volume vs its 20-bar
# SMA instead) so it's intentionally absent here — None means "not gated".
_FIXED_RVOL_GATES = {
    "BOS_MSS":    1.5,
    "FVG":        1.5,
    "TREND_CONT": 1.2,
}


def _real_rvol_gate(strategy_id: str, today: pd.DataFrame, sig) -> float | None:
    """
    Return the RVOL threshold that ACTUALLY applied to a real mined signal —
    read by re-deriving it the same way strategy_router.py's own eval
    functions do, not a static per-strategy assumption.

    Why this exists (2026-06-20): the Playbooks page was showing a fixed
    "needs >= X%" number per strategy that came from stale docstrings/notes,
    not the real code. strategy_router.py's _get_dynamic_rvol_threshold()
    means 4 of the 8 strategies (INST_ORB, VWAP_PB, MID_BRK, CHAN_BREAK) use
    a CONTEXT-DEPENDENT gate that drops from 1.2x to 1.0x once market
    structure is already confirmed — a real example showing "RVOL 1.01x"
    passing a supposedly ">=1.3x" gate was this exact bug, not a fluke.
    This function is read-only and duplicates strategy_router's msa_confirmed
    derivation ONLY for display purposes — it never feeds back into any
    trading decision, so it carries none of the risk a change to the live
    eval functions would.
    """
    last_bar = today.iloc[-1]
    bar_min  = last_bar["time"].hour * 60 + last_bar["time"].minute
    close    = float(last_bar["close"])
    vwap     = float(last_bar["vwap"]) if not pd.isna(last_bar.get("vwap", np.nan)) else None
    msa      = MarketStructureAnalyzer(today)

    if strategy_id == "INST_ORB":
        msa_ok = (msa.confirmed_lower_high() if sig.direction == "bearish"
                  else msa.confirmed_higher_low())
        or_low = sig.meta.get("or_low") if sig.meta else None
        return _get_dynamic_rvol_threshold(bar_min, close, or_low, vwap, "INST_ORB", msa_confirmed=msa_ok)
    if strategy_id == "VWAP_PB":
        msa_ok = (msa.confirmed_lower_high() if sig.direction == "bearish"
                  else msa.confirmed_higher_low())
        return _get_dynamic_rvol_threshold(bar_min, close, None, vwap, "VWAP_PB", msa_confirmed=msa_ok)
    if strategy_id == "MID_BRK":
        or_low = sig.meta.get("or_low") if sig.meta else None
        return _get_dynamic_rvol_threshold(bar_min, close, or_low, vwap, "MID_BRK", msa_confirmed=True)
    if strategy_id == "CHAN_BREAK":
        return _get_dynamic_rvol_threshold(bar_min, close, None, vwap, "CHAN_BREAK", msa_confirmed=True)
    return _FIXED_RVOL_GATES.get(strategy_id)   # fixed gate, or None (AFT_REV — no RVOL floor)
