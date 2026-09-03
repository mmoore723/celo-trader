"""
database/connection.py — Connection context managers: get_conn() opens
the currently-active DB (paper or live, per user_settings), _conn_for_mode()
opens a specific mode's DB regardless of which one is currently active (used
by the Journal/Performance pages' mode toggle).

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import sqlite3
from contextlib import contextmanager

from config import get_db_path
from database.schema import _init_db_at


# ── Connection context manager ────────────────────────────────────────────────

@contextmanager
def get_conn():
    """
    Yield a SQLite connection for the *currently active* trading database.

    The active file is resolved fresh on every call via get_db_path() so that
    toggling paper_trading in the UI takes effect immediately without restart:
      paper_trading = True  → trades_paper.db
      paper_trading = False → trades_live.db

    WAL mode is enabled for safe concurrent readers (dashboard + bot loop).
    Commits on clean exit, rolls back on any exception.
    """
    _active_path = get_db_path()
    conn = sqlite3.connect(str(_active_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _conn_for_mode(mode: str, user_id: str | None = None):
    """
    Yield a read connection to the DB file for the requested mode —
    regardless of which mode the bot is currently running in.

    get_conn() opens whichever DB matches the current bot setting.  That's
    correct for INSERT/UPDATE paths (the bot writes to its active DB).  But
    the Journal and Performance pages use a mode toggle: the user should be
    able to read paper trades while the bot is live and vice-versa.

    Bug without this: get_all_trades(mode="paper") while bot runs live →
    get_conn() opens trades_live.db → WHERE paper=1 → 0 rows always.

    Directory is derived from get_db_path().parent so it works whether the
    DB lives at the project root (single-user) or user_data/{id}/ (multi-user).
    """
    _db_dir  = get_db_path(user_id=user_id).parent
    _path    = _db_dir / f"trades_{mode}.db"
    # Auto-init schema if this DB file is new or was never migrated.
    # _init_db_at uses CREATE TABLE IF NOT EXISTS so it's safe to call every time.
    _init_db_at(_path)
    conn = sqlite3.connect(str(_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

