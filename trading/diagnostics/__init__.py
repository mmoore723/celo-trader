"""
trading/diagnostics/ — Per-tick health checks and bar narrative logging.

Split from the old single trading/diagnostics.py into themed modules
(2026-08-01, file-size cleanup) — no logic changed anywhere, only relocated.
This __init__.py re-exports the exact same public names the old flat module
did, so every existing `from trading.diagnostics import X` call site
elsewhere in the app is unaffected:

  bar_thinking.py     — _log_bar_thinking (kept as one function, see its
                        own docstring)
  ghost_positions.py   — _check_ghost_positions
  orphaned_orders.py    — _sweep_orphaned_orders
"""

from trading.diagnostics.bar_thinking import _log_bar_thinking
from trading.diagnostics.ghost_positions import _check_ghost_positions
from trading.diagnostics.orphaned_orders import _sweep_orphaned_orders

__all__ = ["_log_bar_thinking", "_check_ghost_positions", "_sweep_orphaned_orders"]
