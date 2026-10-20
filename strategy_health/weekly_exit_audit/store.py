"""Audit persistence, physically separate from trading databases."""
import json
import sqlite3
import hashlib
import zlib
from datetime import datetime, timezone


def save(path, key, result, trades):
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path, timeout=10) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS audits(
          id INTEGER PRIMARY KEY,account TEXT,mode TEXT,ticker TEXT,strategy TEXT,version TEXT,
          created TEXT,status TEXT,recommendation TEXT,payload TEXT);
        CREATE INDEX IF NOT EXISTS audit_scope ON audits(account,mode,strategy,version,ticker,id);
        CREATE TABLE IF NOT EXISTS evidence(digest TEXT PRIMARY KEY,payload BLOB);
        CREATE TABLE IF NOT EXISTS audit_trades(audit_id INTEGER,trade_id INTEGER,digest TEXT,
          PRIMARY KEY(audit_id,trade_id));
        """)
        result = {**result, "ticker": key[2], "strategy": key[3], "version": key[4], "mode": key[1], "created": now}
        audit_id = conn.execute("INSERT INTO audits(account,mode,ticker,strategy,version,created,status,recommendation,payload) VALUES(?,?,?,?,?,?,?,?,?)",
            (*key, now, result["status"], result["recommendation"],
             zlib.compress(json.dumps(result, allow_nan=False).encode()))).lastrowid
        for trade in trades:
            payload = json.dumps(trade, sort_keys=True, allow_nan=False).encode()
            digest = hashlib.sha256(payload).hexdigest()
            conn.execute("INSERT OR IGNORE INTO evidence VALUES(?,?)", (digest, zlib.compress(payload)))
            conn.execute("INSERT INTO audit_trades VALUES(?,?,?)", (audit_id, trade["id"], digest))
    return audit_id


def read(path, account, mode, audit_id=None):
    if not path.exists() or not account:
        return None if audit_id is not None else []
    with sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=3) as conn:
        conn.row_factory = sqlite3.Row
        if audit_id is not None:
            row = conn.execute("SELECT payload FROM audits WHERE id=? AND account=? AND mode=?",
                               (audit_id, account, mode)).fetchone()
            return json.loads(zlib.decompress(row["payload"])) if row else None
        return [dict(r) for r in conn.execute("""
            SELECT id,ticker,strategy,version,created,status,recommendation FROM audits
            WHERE account=? AND mode=? AND id IN
            (SELECT MAX(id) FROM audits WHERE account=? AND mode=? GROUP BY ticker,strategy,version)
            ORDER BY strategy,version,ticker
        """, (account, mode, account, mode))]
