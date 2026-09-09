"""
scanner/ — Dynamic daily universe builder + intra-session rescore.

Split from the old single scanner.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports the exact same public (and externally-used private)
names the old flat module did, so every existing `from scanner import X`
call site elsewhere in the app is unaffected:

  constants.py — ticker universe/blacklist/ETF set, timing windows, thresholds
  helpers.py    — _et_now, _hm_in_range, _compute_atr
  state_io.py    — disk read/write for scanner_state.json / daily_universe.json
  premarket.py    — daily_premarket_scan (Phase 1, kept as one function --
                    see its own docstring)
  scoring.py        — _score_ticker helper and locked daily run_scan
  windows.py          — is_premarket_window, is_scan_window, get_watchlist,
                        get_today_universe

Daily operation
───────────────
Phase 1  (once during the premarket window each day):
    daily_premarket_scan() discovers Alpaca's active optionable universe,
    screens snapshots and daily history, balances the existing strategy
    families, and writes the top 30 research candidates to disk. The reviewed
    LIQUID_POOL remains only a network-failure fallback.

Every subsequent run_scan() call reuses that same morning universe and order.
"""

from scanner.constants import (
    SCANNER_STATE, DAILY_UNIVERSE_PATH, _ETF_SET, TICKER_BLACKLIST,
    LIQUID_POOL, ANCHOR_TICKERS, SCAN_UNIVERSE,
    PREMARKET_START_HM, PREMARKET_END_HM, SESSION_START_HM, SESSION_END_HM,
    _MIN_PRICE, _MIN_AVG_DAILY_VOL, _MIN_GAP_PCT, _MAX_GAP_PCT,
    _MIN_RVOL, _MIN_RVOL_ETF, _MIN_GAP_PCT_ETF, _MIN_ATR_DOLLARS,
    _ATR_MIN_DOLLARS, _ATR_MIN_PCT,
)
from scanner.helpers import _et_now, _hm_in_range, _compute_atr
from scanner.state_io import _write_state, _write_daily_universe, _read_daily_universe
from scanner.premarket import daily_premarket_scan
from scanner.scoring import _score_ticker, run_scan
from scanner.windows import get_watchlist, get_today_universe, is_premarket_window, is_scan_window

__all__ = [
    "SCANNER_STATE", "DAILY_UNIVERSE_PATH", "_ETF_SET", "TICKER_BLACKLIST",
    "LIQUID_POOL", "ANCHOR_TICKERS", "SCAN_UNIVERSE",
    "PREMARKET_START_HM", "PREMARKET_END_HM", "SESSION_START_HM", "SESSION_END_HM",
    "_MIN_PRICE", "_MIN_AVG_DAILY_VOL", "_MIN_GAP_PCT", "_MAX_GAP_PCT",
    "_MIN_RVOL", "_MIN_RVOL_ETF", "_MIN_GAP_PCT_ETF", "_MIN_ATR_DOLLARS",
    "_ATR_MIN_DOLLARS", "_ATR_MIN_PCT",
    "_et_now", "_hm_in_range", "_compute_atr",
    "_write_state", "_write_daily_universe", "_read_daily_universe",
    "daily_premarket_scan", "_score_ticker", "run_scan",
    "get_watchlist", "get_today_universe", "is_premarket_window", "is_scan_window",
]
