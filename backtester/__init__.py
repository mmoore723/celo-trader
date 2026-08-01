"""
backtester/ — Full-Strategy Historical Simulation Engine.

Split from the old single backtester.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports Backtester, the only name every existing
`from backtester import X` call site elsewhere in the app actually uses.

  helpers.py     — quiet-logging, IV lookup, simplified option pricer
  core.py        — CoreMixin      (__init__, contract sizing)
  fetch.py       — FetchMixin     (extra-timeframe fetch, entry-source prep)
  market_data.py — MarketDataMixin (cached fetch-and-precompute pipeline)
  run.py         — RunMixin       (run(): the public entry point)
  simulate.py    — SimulateMixin  (_simulate_day: per-day replay loop)
  close.py       — CloseMixin     (_close_bt_trade: trade recorder)
  results.py     — ResultsMixin   (_compute_results: summary stats)
  engine.py      — Backtester (assembles all mixins above + shared constants)

Replays N months of historical 5-min OHLCV bars through all live strategy
modules using the SAME quality gates, sizing, and exit logic as the live bot
(confidence floor, conflict veto, ADX regime gate, session windows, 4-tier
risk ladder, staged exits, 5% slippage per side).

Output: overall P&L / win rate / Sharpe / drawdown, per-strategy breakdown,
daily P&L, exit-reason breakdown, and full trade log.
"""

from backtester.engine import Backtester

__all__ = ["Backtester"]
