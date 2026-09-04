"""Critical execution state, separate from best-effort network audit events."""
import fcntl
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


@contextmanager
def connect(path):
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS execution_recovery (
            id TEXT PRIMARY KEY, account TEXT NOT NULL, symbol TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, body TEXT NOT NULL,
            updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS execution_one_active
            ON execution_recovery(account, symbol) WHERE active = 1""")
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save(conn, record):
    conn.execute("""INSERT INTO execution_recovery VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET active=excluded.active, body=excluded.body,
        updated_at=excluded.updated_at""", (
        record["id"], record["account"], record["symbol"], int(record["active"]),
        json.dumps(record, allow_nan=False), datetime.now(timezone.utc).isoformat(),
    ))


class RecoveryStore:
    def __init__(self, path, account):
        self.path, self.account = path, account
        self.journal_account, self.aliases = account, {account}

    @contextmanager
    def lock(self, symbol):
        """Nonblocking OS lock covers threads/processes; restart releases it."""
        directory = self.path.parent / ".order_locks"
        directory.mkdir(exist_ok=True)
        key = hashlib.sha256(f"{self.path.name}:{self.account}:{symbol}".encode()).hexdigest()
        with (directory / key).open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def pending(self, symbol=None):
        with connect(self.path) as conn:
            rows = conn.execute("""SELECT body FROM execution_recovery
                WHERE active=1 AND account=? AND (? IS NULL OR symbol=?)""",
                (self.account, symbol, symbol)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, record):
        with connect(self.path) as conn:
            save(conn, record)
