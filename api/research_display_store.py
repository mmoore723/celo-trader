"""Tenant-scoped display snapshots. Never used to authorize an order."""
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing


def _path():
    from config.paths import get_user_data_dir
    return get_user_data_dir(create=False) / "research_display.sqlite3"


def _key(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def load(scope):
    path = _path()
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=.1)) as conn:
            row = conn.execute("SELECT created,payload FROM snapshots WHERE key=?", (_key(scope),)).fetchone()
        return (row[0], json.loads(zlib.decompress(row[1]))) if row else None
    except (sqlite3.Error, ValueError, zlib.error):
        return None


def save(scope, created, payload):
    path = _path()
    if not path.parent.is_dir():
        return
    with closing(sqlite3.connect(path, timeout=1)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS snapshots(key TEXT PRIMARY KEY,created REAL,payload BLOB)")
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?)",
                     (_key(scope), created, zlib.compress(json.dumps(payload).encode())))
        conn.execute("DELETE FROM snapshots WHERE key NOT IN (SELECT key FROM snapshots ORDER BY created DESC LIMIT 12)")
