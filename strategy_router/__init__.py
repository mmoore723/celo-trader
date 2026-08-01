"""
strategy_router/__init__.py — Dynamic Multi-Strategy Signal Router

Thin orchestrator: builds the indicator frame once per tick, calls each
strategy module's evaluate() function, runs the signal through the quality
gates in router_gates.py, and returns the survivors ranked by confidence.
All evaluation logic lives in strategies/; all post-evaluation filtering
lives in router_gates.py; regime classification lives in regime_manager.py.
This file only wires them together (2026-07-16 split — was 830 lines).

Strategy IDs (nine active, one OFF by default):
  GAP_GO      — strategies/gap_go.py    (09:30–09:45)
  INST_ORB    — strategies/inst_orb.py   (09:45–10:30)
  VWAP_PB     — strategies/vwap_pb.py   (09:45–EOD)
  FVG         — strategies/fvg.py        (09:45–EOD)  ← absorbs BOS_MSS sweep logic
  MID_BRK     — strategies/mid_brk.py   (10:30–13:00)  ← OFF by default, negative expectancy
  AFT_REV     — strategies/aft_rev.py   (13:00–15:30)
  TREND_CONT  — strategies/trend_cont.py (09:45–14:30)
  CHAN_BREAK  — strategies/chan_break.py (09:45–14:00)  ← disabled, 0% WR in backtests
  LIQ_SWEEP   — strategies/liquidity_sweep.py (09:45–15:30)  ← fades a swept swing high/low

  BOS_MSS (strategies/bos_mss.py) — DISABLED; its sweep detection was merged
  into FVG as a confidence modifier (running both double-voted the same move).

All signals pass through RiskManager gates in risk.py before entry:
  • 1% risk rule  • 1.6 R:R minimum  • 20% hard stop  • time-box exit

Split (2026-08-01, file-size cleanup) out of the old single
strategy_router.py into evaluators.py (ACTIVE_STRATEGIES table),
indicator_frame.py (_build_indicator_frame), and route.py (route_signals);
no logic changed, only relocated.

_MIN_CONFIDENCE and ADX_GATED_STRATEGIES are defined/re-exported HERE (not
in route.py) because two archived A/B test scripts monkey-patch them
directly on the PACKAGE object at runtime — `strategy_router._MIN_CONFIDENCE
= floor` (scripts/ab_tests/ab_test_confidence_floor.py) and
`strategy_router.ADX_GATED_STRATEGIES = _orig - {"MID_BRK"}`
(scripts/ab_tests/ab_test_mid_brk_adx_gate.py) — expecting that mutation to
change route_signals()'s live behavior. route.py's route_signals() reads
both via a live dotted lookup on this package object at call time (see
route.py's own docstring for the mechanics), so this __init__ module's
namespace is the actual mutable home for both knobs, exactly matching the
original single-file module's semantics.
"""

from __future__ import annotations

import logging

# ── Re-export Signal + MSA so callers that import from strategy_router still work ─
from strategies.base import Signal, MarketStructureAnalyzer  # noqa: F401

# ── Regime classification (trend direction + trend strength) ─────────────────
from regime_manager import (
    ADX_MIN, ADX_GATED_STRATEGIES, compute_adx, compute_adx_series,  # noqa: F401 (re-exported)
)

from strategy_router.evaluators import ACTIVE_STRATEGIES
from strategy_router.indicator_frame import _build_indicator_frame
from strategy_router.route import route_signals

logger = logging.getLogger("celo_trader.strategy_router")

# ── Router quality gates ───────────────────────────────────────────────────────
# Confidence floor: strategies score 0.75 at baseline with zero bonuses.
# Anything below is a marginal signal with no meaningful edge — drop it.
_MIN_CONFIDENCE = 0.74   # confidence floor — below this is noise, not edge

# Conflict veto window: if the top two signals disagree on direction AND their
# confidence scores are within this band, the router is ambiguous — return nothing.
_CONFLICT_VETO_BAND = 0.05

# Session bias penalty fallback default — the real value is computed
# dynamically per-tick in router_gates.apply_session_bias_penalty().
_SESSION_BIAS_PENALTY = 0.05

__all__ = [
    "Signal",
    "MarketStructureAnalyzer",
    "ADX_MIN",
    "ADX_GATED_STRATEGIES",
    "compute_adx",
    "compute_adx_series",
    "ACTIVE_STRATEGIES",
    "_build_indicator_frame",
    "route_signals",
    "logger",
    "_MIN_CONFIDENCE",
    "_CONFLICT_VETO_BAND",
    "_SESSION_BIAS_PENALTY",
]
