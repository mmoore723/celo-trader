"""
strategy_router/__init__.py — Dynamic Multi-Strategy Signal Router

Thin orchestrator: builds the indicator frame once per tick, calls each
strategy module's evaluate() function, runs the signal through the quality
gates in router_gates.py, and returns the survivors ranked by confidence.
All evaluation logic lives in strategies/; all post-evaluation filtering
lives in router_gates.py; regime classification lives in regime_manager.py.
This file only wires them together (2026-07-16 split — was 830 lines).

Production strategy IDs:
  V2_ORB_PULLBACK
  V2_SPY_TREND_CONT
  V2_SPY_AFTERNOON_FVG
  V2_TSLA_TWO_LEG_TREND_PULLBACK (one-minute injected execution path)

All signals pass through RiskManager gates in risk.py before entry:
  • 1% risk rule  • 1.6 R:R minimum  • 20% hard stop  • time-box exit

Split (2026-08-01, file-size cleanup) out of the old single
strategy_router.py into evaluators.py (ACTIVE_STRATEGIES table),
indicator_frame.py (_build_indicator_frame), and route.py (route_signals);
no logic changed, only relocated.

The shared confidence and ADX settings remain package attributes for the
router's normal live lookup; production contains no A/B-test monkey patches.
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
