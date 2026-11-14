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
import re
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt as _bcrypt_lib

logger = logging.getLogger("celo_trader.auth.users")

# ── Password complexity ───────────────────────────────────────────────────────

_SPECIAL = r"[!@#$%^&*()\-_=+\[\]{}|;:,.<>?/~`'\"]"
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


def normalize_username(username: str) -> str:
    value = username.strip().lower()
    if not _USERNAME.fullmatch(value):
        raise ValueError(
            "Username must be 3–32 characters and use only letters, numbers, dots, dashes, or underscores"
        )
    return value

def validate_password(password: str) -> None:
    """
    Raise ValueError with a descriptive message if the password fails
    any complexity requirement.  Called by create_user() and reset_password()
    so the same rules apply everywhere — register, admin create, admin reset.

    Requirements:
      • 12 or more characters
      • At least one uppercase letter  (A-Z)
      • At least one lowercase letter  (a-z)
      • At least one digit             (0-9)
      • At least one special character (!@#$%^&* etc.)
    """
    failures = []
    if len(password) < 12:
        failures.append("at least 12 characters")
    if len(password.encode("utf-8")) > 72:
        failures.append("no more than 72 UTF-8 bytes")
    if not re.search(r"[A-Z]", password):
        failures.append("one uppercase letter")
    if not re.search(r"[a-z]", password):
        failures.append("one lowercase letter")
    if not re.search(r"\d", password):
        failures.append("one number")
    if not re.search(_SPECIAL, password):
        failures.append("one special character (!@#$%^&* …)")
    if failures:
        raise ValueError("Password must contain: " + ", ".join(failures))


# passlib 1.7.4 is incompatible with bcrypt >= 4.0 (passlib's internal
# detect_wrap_bug test uses a >72-byte string which bcrypt 4+ rejects).
# Use the bcrypt package directly instead.
# bcrypt hard-limits at 72 bytes — always truncate before hashing/verifying.
def _hash_pw(plain: str) -> str:
    return _bcrypt_lib.hashpw(plain.encode(), _bcrypt_lib.gensalt()).decode()

def _verify_pw(plain: str, hashed: str) -> bool:
    try:
        if len(plain.encode("utf-8")) > 72:
            return False
        return _bcrypt_lib.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

_ROOT    = Path(__file__).resolve().parents[1]
_DB_PATH = _ROOT / "user_data" / "users.db"
_DATA    = _ROOT / "user_data"


# ── Terms of Service version ──────────────────────────────────────────────────
# Bump this string whenever the ToS text changes.  All users who accepted an
# older version will be re-prompted on next login.
CURRENT_TERMS_VERSION = "1.0"


# ── DB bootstrap ──────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Open (and initialise) the users database. Thread-safe due to WAL mode."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                TEXT PRIMARY KEY,
            username          TEXT UNIQUE NOT NULL,
            pw_hash           TEXT NOT NULL,
            is_admin          INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL,
            terms_accepted_at TEXT,
            terms_version     TEXT,
            session_version   INTEGER NOT NULL DEFAULT 1
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
    _run_migrations(conn)   # add any columns missing from older DB files
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Non-destructive column additions for schema upgrades."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for col, typedef in [
        ("terms_accepted_at", "TEXT"),
        ("terms_version",     "TEXT"),
        ("session_version",   "INTEGER NOT NULL DEFAULT 1"),
        ("access_profile", "TEXT NOT NULL DEFAULT 'legacy'"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
    if "access_profile" not in {r[1] for r in conn.execute("PRAGMA table_info(invites)")}:
        conn.execute("ALTER TABLE invites ADD COLUMN access_profile TEXT NOT NULL DEFAULT 'watch'")
    conn.commit()


def _migrate_admin_if_needed(conn: sqlite3.Connection) -> None:
    """
    If no users exist yet, create the admin account from the existing
    DASHBOARD_PASSWORD / DASHBOARD_PASSWORD_HASH env vars so the current
    operator's login keeps working unchanged.
    """
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return

    pw_hash = os.getenv("DASHBOARD_PASSWORD_HASH", "")
    pw_plain = os.getenv("DASHBOARD_PASSWORD", "")
    if not pw_hash:
        if not pw_plain:
            raise RuntimeError(
                "Initial admin bootstrap requires DASHBOARD_PASSWORD_HASH or DASHBOARD_PASSWORD"
            )
        validate_password(pw_plain)
        pw_hash = _hash_pw(pw_plain)
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


def _initialize_member_templates(uid: str) -> None:
    """Only new member accounts get an explicit all-off template selection."""
    from config.atomic_files import atomic_write_json
    from config.defaults import _DEFAULTS
    from config.strategy_catalog import REVIEWED_STRATEGIES
    target = _DATA / uid / 'settings.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    updates = {key: False for key in _DEFAULTS
               if key.startswith(('strategy_', 'observe_')) and key.endswith('_enabled')}
    updates.update({rule.setting_key: False for rule in REVIEWED_STRATEGIES.values()})
    updates.update(strategy_pair_approvals={}, strategy_ticker_consents={}, research_strategy_ids=[])
    atomic_write_json(target, updates)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_user(username: str, password: str, is_admin: bool = False,
                user_id: Optional[str] = None, access_profile: str = "legacy") -> dict:
    """Create a new user. Returns the user dict. Raises ValueError on duplicate or weak password."""
    if access_profile not in {"legacy", "watch", "learning"}:
        raise ValueError("Unknown access profile")
    validate_password(password)          # raises ValueError if requirements not met
    normalized = normalize_username(username)
    uid     = user_id or str(uuid.uuid4())[:8]
    pw_hash = _hash_pw(password)
    conn    = get_db()
    try:
        conn.execute(
            "INSERT INTO users (id, username, pw_hash, is_admin, created_at, access_profile) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, normalized, pw_hash, 1 if is_admin else 0, _now(), access_profile),
        )
        if not is_admin:
            _initialize_member_templates(uid)
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' is already taken")
    finally:
        conn.close()

    # Create the user's data directory
    (_DATA / uid).mkdir(parents=True, exist_ok=True)
    logger.info("User created: id=%s username=%s admin=%s", uid, normalized, is_admin)
    return {"user_id": uid, "username": normalized, "is_admin": is_admin, "session_version": 1, "access_profile": access_profile}


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
        if not _verify_pw(password, row["pw_hash"]):
            return None
    except Exception:
        return None
    return {"user_id": row["id"], "username": row["username"],
            "is_admin": bool(row["is_admin"]), "session_version": int(row["session_version"]),
            "terms_version": row["terms_version"], "access_profile": row["access_profile"]}


def get_user(user_id: str) -> Optional[dict]:
    conn = get_db()
    row  = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id":       row["id"],
        "username":      row["username"],
        "is_admin":      bool(row["is_admin"]),
        "terms_version": row["terms_version"],  # None if never accepted
        "session_version": int(row["session_version"]),
        "access_profile": row["access_profile"],
    }


def accept_terms(user_id: str, version: str = CURRENT_TERMS_VERSION) -> bool:
    """Record that the user accepted the given ToS version. Returns True on success."""
    conn = get_db()
    cur  = conn.execute(
        "UPDATE users SET terms_accepted_at = ?, terms_version = ? WHERE id = ?",
        (_now(), version, user_id),
    )
    conn.commit()
    conn.close()
    logger.info("Terms v%s accepted by user_id=%s", version, user_id)
    return cur.rowcount > 0


def list_users() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, is_admin, created_at, access_profile FROM users ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [{"user_id": r["id"], "username": r["username"],
             "is_admin": bool(r["is_admin"]), "created_at": r["created_at"], "access_profile": r["access_profile"]} for r in rows]


def reset_password(user_id: str, new_password: str) -> bool:
    """Set a new password for any user. Returns False if user not found."""
    validate_password(new_password)      # raises ValueError if requirements not met
    pw_hash = _hash_pw(new_password)
    conn = get_db()
    cur  = conn.execute(
        "UPDATE users SET pw_hash = ?, session_version = session_version + 1 WHERE id = ?",
        (pw_hash, user_id),
    )
    conn.commit()
    conn.close()
    logger.info("Password reset for user_id=%s", user_id)
    return cur.rowcount > 0


def delete_user(user_id: str) -> bool:
    if user_id == "admin":
        raise ValueError("Cannot delete the primary admin account")
    conn = get_db()
    cur  = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Invite tokens ─────────────────────────────────────────────────────────────

def create_invite(created_by: str, hours: int = 48, access_profile: str = "watch") -> str:
    """Create a single-use invite token valid for `hours` hours."""
    if access_profile not in {"watch", "learning"}:
        raise ValueError("Invites support Watch-only or Learning access")
    if not 1 <= int(hours) <= 168:
        raise ValueError("Invite validity must be between 1 and 168 hours")
    token      = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    conn       = get_db()
    conn.execute(
        "INSERT INTO invites (token, created_by, expires_at, access_profile) VALUES (?, ?, ?, ?)",
        (token, created_by, expires_at, access_profile),
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


def create_user_from_invite(token: str, username: str, password: str) -> dict:
    """Consume an invite and create its user in one atomic transaction."""
    validate_password(password)
    normalized = normalize_username(username)
    uid = str(uuid.uuid4())[:8]
    pw_hash = _hash_pw(password)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT expires_at, access_profile FROM invites WHERE token = ? AND used_by IS NULL", (token,)
        ).fetchone()
        if not row:
            raise ValueError("Invalid or expired invite link")
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires:
            raise ValueError("Invalid or expired invite link")
        conn.execute(
            "INSERT INTO users (id, username, pw_hash, is_admin, created_at, access_profile) VALUES (?, ?, ?, 0, ?, ?)",
            (uid, normalized, pw_hash, _now(), row["access_profile"]),
        )
        _initialize_member_templates(uid)
        used = conn.execute(
            "UPDATE invites SET used_by = ?, used_at = ? WHERE token = ? AND used_by IS NULL",
            (uid, _now(), token),
        )
        if used.rowcount != 1:
            raise ValueError("Invalid or expired invite link")
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(f"Username '{normalized}' is already taken") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    (_DATA / uid).mkdir(parents=True, exist_ok=True)
    logger.info("User registered: id=%s username=%s", uid, normalized)
    return {"user_id": uid, "username": normalized, "is_admin": False, "session_version": 1, "access_profile": row["access_profile"]}
