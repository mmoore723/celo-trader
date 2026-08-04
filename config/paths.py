"""
config/paths.py — Project root anchor, on-disk file paths, and per-user
data-directory helpers.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.

FIX (package-split path bug, same class as tax_engine/constants.py and
scanner/ earlier this session): the old flat config.py lived directly in
the project root, so Path(__file__).resolve().parent pointed at the root.
This file now lives one level deeper at config/paths.py, so the same
expression would resolve to config/ instead — silently pointing BASE_DIR
(and everything derived from it: user_data/, trades.db, log/bot.log,
user_settings.json, .env loading) at the wrong directory. The extra
.parent below accounts for the added nesting depth. Applied proactively
here (not discovered via a bug) because the risk pattern is now well
understood from two earlier incidents this session.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

BASE_DIR      = Path(__file__).resolve().parent.parent   # project root (see FIX note above)
_USER_DATA    = BASE_DIR / "user_data"           # per-user data root
DB_PATH       = BASE_DIR / "trades.db"           # legacy alias — kept so old imports don't break
DB_PATH_PAPER = BASE_DIR / "trades_paper.db"     # legacy — now per-user inside user_data/
DB_PATH_LIVE  = BASE_DIR / "trades_live.db"      # legacy — now per-user inside user_data/
LOG_PATH      = BASE_DIR / "log" / "bot.log"
SETTINGS_PATH = BASE_DIR / "user_settings.json"  # legacy single-user fallback


def _get_user_id() -> str:
    """
    Return the currently authenticated user's ID from the request-scoped ContextVar.
    Falls back to "admin" so all single-user / background-thread code is unchanged.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "admin"


def get_user_data_dir(user_id: str | None = None) -> Path:
    """Return the per-user data directory, creating it if needed."""
    uid = user_id or _get_user_id()
    p   = _USER_DATA / uid
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path(user_id: str | None = None) -> Path:
    """
    Return the active SQLite database path for the given (or current) user.

    Hard separation:
      paper_trading = True  → trades_paper.db  (paper orders / sim trades)
      paper_trading = False → trades_live.db   (real broker fills ONLY)

    Reads settings dynamically so a live toggle takes effect immediately.
    """
    # Lazy import: settings_store.get_settings needs paths.get_user_data_dir,
    # so a top-level import here would be circular.
    from config.settings_store import get_settings
    from config.env_keys import ALPACA_PAPER
    try:
        _s     = get_settings(user_id=user_id)
        _paper = _s.get("paper_trading", ALPACA_PAPER)
    except Exception:
        _paper = ALPACA_PAPER
    _dir  = get_user_data_dir(user_id)
    _name = "trades_paper.db" if _paper else "trades_live.db"
    return _dir / _name


_LEGACY_BOT_STATE_PATH = BASE_DIR / "bot_state.json"  # pre-multi-user location


def get_bot_state_path(user_id: str | None = None) -> Path:
    """
    Return the per-user bot_state.json path (user_data/{user_id}/bot_state.json),
    creating the user's data directory if needed.

    One-time migration: the very first time this is called for a user whose
    per-user file doesn't exist yet, if the legacy root-level bot_state.json
    exists, copy it in so existing "admin" state (account balance, open
    positions, etc.) isn't silently lost when this ships. Only ever applies
    once per user — after the copy, the per-user file is authoritative and
    the legacy file is left untouched (read-only fallback, never written).
    """
    _path = get_user_data_dir(user_id) / "bot_state.json"
    if not _path.exists() and _LEGACY_BOT_STATE_PATH.exists():
        try:
            _path.write_text(_LEGACY_BOT_STATE_PATH.read_text())
        except Exception:
            pass  # non-fatal — worst case the user starts with a fresh state file
    return _path


def load_bot_state_safely(path: Path) -> dict | None:
    """Read a complete bot-state object or treat a partial write as absent."""
    try:
        raw = path.read_text().strip()
        if not raw:
            return None
        state = json.loads(raw)
        return state if isinstance(state, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
