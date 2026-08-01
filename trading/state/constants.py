"""
trading/state/constants.py — project root, timezone helper, watchdog
constants, and the shared logger for the trading/state package.

Split out of the old single trading/state.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging
from datetime import datetime
from pathlib import Path

import pytz as _pytz

# ── Project root — submodules in trading/ use this to write bot_state.json etc.
# NOTE: .parent.parent.parent — this file now lives two directories deeper
# than the original flat trading/state.py (trading/state/constants.py vs
# trading/state.py), so an extra .parent is required to still land on the
# actual project root.
_BOT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Timezone helper ───────────────────────────────────────────────────────────
_ET_TZ = _pytz.timezone("US/Eastern")


def _now_et() -> datetime:
    """Return the current wall-clock time as a tz-aware US/Eastern datetime."""
    return datetime.now(_ET_TZ)


# Network health watchdog constants
_DATA_GAP_WARN_MINUTES  = 5    # alert after this many minutes without a clean bar fetch
_DATA_GAP_PAUSE_MINUTES = 10   # skip strategy evaluation after this many minutes (stale data)

# ── Logger ────────────────────────────────────────────────────────────────────
logger = logging.getLogger("celo_trader.trading_logic")
