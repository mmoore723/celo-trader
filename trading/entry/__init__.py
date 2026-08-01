"""
trading/entry/ — Ticker/contract selection and the main per-tick evaluation.

Split from the old single trading/entry.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports the exact same public names the old flat module did,
so every existing `from trading.entry import X` call site elsewhere in the
app (trading/loop.py imports _tick; api/routes/signals.py imports
select_contract) is unaffected:

  ticker.py    — select_ticker (phase-based ticker selection — confirmed
                 unused in the live tick loop, kept per convention, see
                 its own docstring)
  contract.py  — select_contract (option chain selection)
  skip_log.py  — _skip_log (rejection-reason logging)
  tick.py      — _tick (kept as one function — see its own docstring for
                 why splitting its body would be a rewrite, not a move)
"""

from trading.entry.ticker import select_ticker
from trading.entry.contract import select_contract
from trading.entry.skip_log import _skip_log
from trading.entry.tick import _tick

__all__ = ["select_ticker", "select_contract", "_skip_log", "_tick"]
