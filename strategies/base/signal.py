"""
strategies/base/signal.py — Signal dataclass returned by every strategy
evaluator.

Split out of the old single strategies/base.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(order=True)
class Signal:
    """Ranked by confidence descending (highest first in a sorted list)."""
    confidence:  float
    strategy_id: str          = field(compare=False)
    direction:   str          = field(compare=False)
    rvol:        float        = field(compare=False)
    trigger_bar: pd.Timestamp = field(compare=False)
    meta:        dict         = field(compare=False, default_factory=dict)
