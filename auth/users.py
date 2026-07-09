"""
auth/users.py — Multi-user account management.

Tables:
  users   — id (UUID), username, hashed_password, is_admin, created_at
  invites — token (UUID), created_by, expires_at, used_by, used_at

Data directory: {app_root}/user_data/{user_id}/
  settings.json   — per-user settings (overrides)
  credentials.enc — encrypted Alpaca + Tradier API keys
  trades_paper.db / trades_live.db — isolated trade databases

Migration: on first call to get_db() with no existing users table, the
existing admin account (DASHBOARD_PASSWORD / DASHBOARD_PASSWORD_HASH) is
migrated automatically so the current user sees no change.
"""
from __future__ import annotations
import os
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from passlib.hash import bcrypt as _bcrypt

logger = logging.getLogger("celo_trader.auth.users")

_ROOT    = Path(__file__).resolve().parents[1]
_DB_PATH = _ROOT / "user_data" / "users.db"
_DATA    = _ROOT / "user_data"


# ── DB bootstrap ──────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Open (and initialise) the users database. Thread-safe due to WAL mode."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            username    TEXT UNIQUE NOT NULL,
            pw_hash     TEXT NOT NULL,
            is_admin    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invites (
            token       TEXT PRIMARY KEY,
            created_by  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            used_by     TEXT,
            used_at     TEXT
        )
    """)
    conn.commit()
    _migrate_admin_if_needed(conn)
    return conn


def _migrate_admin_if_needed(conn: sqlite3.Connection) -> None:
    """
    If no users exist yet, create the admin account from the existing
    DASHBOARD_PASSWORD / DASHBOARD_PASSWORD_HASH env vars so the current
    operator's login keeps working unchanged.
    """
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return

    pw_hash = os.getenv("DASHBOARD_PASSWORD_HASH", "")
    pw_plain = os.getenv("DASHBOARD_PASSWORD", "celo2024")
    if not pw_hash:
        pw_hash = _bcrypt.hash(pw_plain)
        logger.info("Migration: hashed DASHBOARD_PASSWORD for admin user")

    admin_id = "admin"
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, pw_hash, is_admin, created_at) "
        "VALUES (?, ?, ?, 1, ?)",
        (admin_id, "admin", pw_hash, _now()),
    )
    conn.commit()

    # Migrate existing trade databases into user_data/admin/
    _user_dir = _DATA / admin_id
    _user_dir.mkdir(parents=True, exist_ok=True)
    for _fname in ("trades_paper.db", "trades_live.db", "user_settings.json"):
        _src = _ROOT / _fname
        _dst = _user_dir / _fname
        if _src.exists() and not _dst.exists():
            import shutil
            shutil.copy2(_src, _dst)
            logger.info("Migration: copied %s → user_data/admin/%s", _fname, _fname)

    logger.info("Migration: admin user created (user_id=admin)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_user(username: str, password: str, is_admin: bool = False,
                user_id: Optional[str] = None) -> dict:
    """Create a new user. Returns the user dict. Raises ValueError on duplicate."""
    uid     = user_id or str(uuid.uuid4())[:8]
    pw_hash = _bcrypt.hash(password)
    conn    = get_db()
    try:
        conn.execute(
            "INSERT INTO users (id, username, pw_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, username.strip().lower(), pw_hash, 1 if is_admin else 0, _now()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' is already taken")
    finally:
        conn.close()

    # Create the user's data directory
    (_DATA / uid).mkdir(parents=True, exist_ok=True)
    logger.info("User created: id=%s username=%s admin=%s", uid, username, is_admin)
    return {"id": uid, "username": username, "is_admin": is_admin}


def authenticate(username: str, password: str) -> Optional[dict]:
    """Return user dict if credentials are valid, else None."""
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        if not _bcrypt.verify(password, row["pw_hash"]):
            return None
    except Exception:
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def get_user(user_id: str) -> Optional[dict]:
    conn = get_db()
    row  = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def list_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "username": r["username"],
             "is_admin": bool(r["is_admin"]), "created_at": r["created_at"]} for r in rows]


def delete_user(user_id: str) -> bool:
    if user_id == "admin":
        raise ValueError("Cannot delete the primary admin account")
    conn = get_db()
    cur  = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Invite tokens ─────────────────────────────────────────────────────────────

def create_invite(created_by: str, hours: int = 48) -> str:
    """Create a single-use invite token valid for `hours` hours."""
    token      = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    conn       = get_db()
    conn.execute(
        "INSERT INTO invites (token, created_by, expires_at) VALUES (?, ?, ?)",
        (token, created_by, expires_at),
    )
    conn.commit()
    conn.close()
    logger.info("Invite created by %s, expires %s", created_by, expires_at)
    return token


def consume_invite(token: str) -> bool:
    """
    Validate that the invite exists, is unused, and is not expired.
    Does NOT mark it used yet — call mark_invite_used() after successful registration.
    Returns True if the token is valid.
    """
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM invites WHERE token = ? AND used_by IS NULL", (token,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def mark_invite_used(token: str, used_by: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE invites SET used_by = ?, used_at = ? WHERE token = ?",
        (used_by, _now(), token),
    )
    conn.commit()
    conn.close()
