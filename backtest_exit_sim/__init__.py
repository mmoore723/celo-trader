"""
backtest_exit_sim/__init__.py — Real exit-engine bridge for the backtester.

Calls risk.py's real RiskManager.evaluate_exit_conditions() — the same
function live trading uses (structural stop -> ATR/swing trail -> VWAP+
trend-dead -> stage1/stage2 -> momentum-death -> time caps) — instead of
backtester.py's old hand-copied approximation. The ATR-trail multiplier
itself (widens with 1h trend support, tightens on 5m RSI exhaustion/MACD
fade/15m swing proximity) is real too — see backtest_trail_multiplier.py,
split out to keep both files under 200 lines. Fails open to the flat base
multiplier if the extra 1h/15m fetch is missing, same as live's own fallback.

Split (2026-08-01, file-size cleanup) out of the old single
backtest_exit_sim.py into constants.py, state.py (ExitSimState),
risk_instance.py (the shared _risk RiskManager instance), trail.py
(_update_trail_and_vwap), and evaluate.py (evaluate_bt_exit); no logic
changed, only relocated.

_risk note: three archived A/B test scripts (scripts/ab_tests/
ab_test_stage1_dynamic.py, ab_test_momentum_fade_tuning.py,
ab_test_stage1_target.py) do `import backtest_exit_sim` then mutate
attributes directly on `backtest_exit_sim._risk`, e.g.
`backtest_exit_sim._risk.ORB_STAGE1_GAIN = value`. This works correctly
after the split with a plain re-export (no live-dotted-lookup trick
needed, unlike strategies/vwap_pb.py's scalar constants) because `_risk` is
a single shared RiskManager OBJECT, constructed exactly once in
risk_instance.py — every consumer (this __init__, trail.py, evaluate.py)
imports that same object by reference, and attribute mutation on a live
object is always visible through every reference to it, regardless of
which file did the mutating or which file is doing the reading.
"""

from backtest_exit_sim.constants import _TRAIL_PROFIT_GATE, _INITIAL_ATR_MULT
from backtest_exit_sim.state import ExitSimState
from backtest_exit_sim.risk_instance import _risk
from backtest_exit_sim.trail import _update_trail_and_vwap
from backtest_exit_sim.evaluate import evaluate_bt_exit

__all__ = [
    "_TRAIL_PROFIT_GATE",
    "_INITIAL_ATR_MULT",
    "ExitSimState",
    "_risk",
    "_update_trail_and_vwap",
    "evaluate_bt_exit",
]
