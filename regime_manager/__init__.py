"""
regime_manager/ — Optional macro-trend regime classifier (2026-07-16).

Background
──────────
VWAP_PB and AFT_REV are currently disabled by default (proven negative
backtest expectancy — see trading/entry.py _STRAT_DEFAULTS for the numbers).
A proposal came in that they're actually failing because nothing enforces a
shared trend direction across strategies: VWAP_PB should only buy pullbacks
WITH the prevailing trend, and AFT_REV should be blocked from taking
reversal trades AGAINST a strong prevailing trend.

Two claims in that proposal did not hold up when checked against the code:
VWAP_PB already has an ADX >= 25 gate (ADX_GATED_STRATEGIES below)
and still lost money with it; and the router already prevents two strategies
opening opposing trades on the same ticker in the same tick (single
top-confidence signal + conflict veto). So this module is not "the missing
piece" that guarantees a fix — it's a genuinely new, untested mechanism
(classify the macro trend on a HIGHER timeframe — 15-min EMA9/21 — than any
individual strategy currently checks) that deserves an honest A/B test
before anything is re-enabled live.

REGIME_GATE_ENABLED defaults to False. Flipping it does nothing to live
trading by itself — VWAP_PB and AFT_REV stay disabled in
trading/entry.py._STRAT_DEFAULTS regardless, until a backtest with this
gate ON actually shows positive expectancy. See ab_test_regime_manager.py.

Split (2026-08-01, file-size cleanup) out of the old single
regime_manager.py into:
  - regime.py: trend DIRECTION classifier (REGIME_* constants,
    compute_regime_series, compute_regime, regime_allows)
  - adx.py:    trend STRENGTH gate (ADX_* constants, compute_adx_series,
    compute_adx)

REGIME_GATE_ENABLED is monkey-patched externally via
`import regime_manager as _regime_mgr; _regime_mgr.REGIME_GATE_ENABLED = X`
(router_gates/regime.py reads it the same way) — see regime.py's docstring
for why this already works correctly across the package split with no
extra lazy-lookup trick needed.
"""
from __future__ import annotations

from regime_manager.regime import (
    REGIME_GATE_ENABLED,
    REGIME_TIMEFRAME,
    REGIME_EMA_FAST,
    REGIME_EMA_SLOW,
    REGIME_GATED_STRATEGIES,
    compute_regime_series,
    compute_regime,
    regime_allows,
)
from regime_manager.adx import (
    ADX_PERIOD,
    ADX_MIN,
    ADX_GATED_STRATEGIES,
    compute_adx_series,
    compute_adx,
)

__all__ = [
    "REGIME_GATE_ENABLED",
    "REGIME_TIMEFRAME",
    "REGIME_EMA_FAST",
    "REGIME_EMA_SLOW",
    "REGIME_GATED_STRATEGIES",
    "compute_regime_series",
    "compute_regime",
    "regime_allows",
    "ADX_PERIOD",
    "ADX_MIN",
    "ADX_GATED_STRATEGIES",
    "compute_adx_series",
    "compute_adx",
]
