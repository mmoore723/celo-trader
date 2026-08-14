"""Shared ADX trend-strength calculation used by the signal router."""
from regime_manager.adx import ADX_PERIOD, ADX_MIN, ADX_GATED_STRATEGIES, compute_adx_series, compute_adx

__all__ = ["ADX_PERIOD", "ADX_MIN", "ADX_GATED_STRATEGIES", "compute_adx_series", "compute_adx"]
