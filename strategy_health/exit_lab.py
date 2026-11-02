"""Persisted Exit Lab read model. No broker, order or policy-selection writes.

Only an offline/background publisher writes this database. HTTP readers never
create it, calculate performance, repair evidence or launch a worker.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {'awaiting approval', 'collecting', 'blocked', 'complete'}
RECOMMENDATIONS = {'KEEP BASELINE', 'INSUFFICIENT EVIDENCE', 'PROPOSE CHANGE'}


def bucket_id(account, mode, strategy, ticker, version, revision):
    return hashlib.sha256(json.dumps([account, mode, strategy, ticker, version, revision]).encode()).hexdigest()


def publish(path, account, mode, summary, detail, trades=()):
    """Atomically publish one precomputed bucket; never called by a GET route."""
    if not account or mode not in {'paper', 'live'}:
        raise ValueError('Explicit account and mode required')
    if summary['status'] not in STATUSES or summary['recommendation'] not in RECOMMENDATIONS:
        raise ValueError('Invalid status or recommendation')
    if summary.get('result_kind') not in {'hypothetical shadow', 'broker-confirmed paper', 'broker-confirmed live'}:
        raise ValueError('Result provenance required')
    identity = bucket_id(account, mode, summary['strategy'], summary['ticker'], summary['version'], summary['revision'])
    payload = dict(summary, id=identity, mode=mode, updated_at=datetime.now(timezone.utc).isoformat())
    paper, live = payload.get('paper_policy'), payload.get('live_policy')
    payload['policy_match'] = 'UNVERIFIED' if not paper or not live else ('MATCHED' if paper == live else 'MISMATCH')
    encoded = json.dumps(payload, allow_nan=False)
    details = json.dumps(detail, allow_nan=False)
    rows = [(identity, i, json.dumps(t, allow_nan=False)) for i, t in enumerate(trades)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''CREATE TABLE IF NOT EXISTS buckets (
            id TEXT PRIMARY KEY, account TEXT NOT NULL, mode TEXT NOT NULL,
            summary TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS bucket_scope ON buckets(account,mode);
            CREATE TABLE IF NOT EXISTS comparisons (
            bucket TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(bucket,ordinal));''')
        with conn:
            conn.execute('INSERT OR REPLACE INTO buckets VALUES (?,?,?,?,?)', (identity, account, mode, encoded, details))
            conn.execute('DELETE FROM comparisons WHERE bucket=?', (identity,))
            conn.executemany('INSERT INTO comparisons VALUES (?,?,?)', rows)
    return identity


def read(path, account, mode, identity=None, page=None):
    """Indexed read-only queries, scoped even when a caller guesses a bucket ID."""
    path = Path(path)
    if not account or mode not in {'paper', 'live'} or not path.is_file():
        return None if identity else {'buckets': [], 'capture_state': 'No published Exit Lab snapshot'}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
        conn.execute('PRAGMA query_only=ON')
        if identity is None:
            rows = conn.execute('SELECT summary FROM buckets WHERE account=? AND mode=? ORDER BY id', (account, mode))
            return {'buckets': [json.loads(r[0]) for r in rows], 'capture_state': 'Persisted results only'}
        row = conn.execute('SELECT detail FROM buckets WHERE id=? AND account=? AND mode=?', (identity, account, mode)).fetchone()
        if row is None:
            return None
        if page is None:
            return json.loads(row[0])
        if not isinstance(page, int) or page < 1:
            raise ValueError('Positive page required')
        rows = list(conn.execute('SELECT payload FROM comparisons WHERE bucket=? ORDER BY ordinal LIMIT 51 OFFSET ?', (identity, (page-1)*50)))
        return {'rows': [json.loads(r[0]) for r in rows[:50]], 'page': page, 'has_more': len(rows)>50}


def seed_inventory(user):
    """Background preflight publisher. Does not score or approve experiments."""
    from auth.context import set_current_user
    from config import get_settings
    from config.paths import get_user_data_dir
    from config.strategy_catalog import public_strategy_catalog
    import subprocess
    set_current_user(user, user, False)
    settings = get_settings()
    account = settings.get('active_broker_account_id')
    mode = 'paper' if settings.get('paper_trading', True) else 'live'
    if not account:
        raise ValueError('No active broker account')
    path = get_user_data_dir(create=False) / 'exit_lab.sqlite3'
    existing = {r['id'] for r in read(path, account, mode)['buckets']}
    revision = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
    added = 0
    for strategy in public_strategy_catalog(settings):
        for ticker in strategy.get('trading_tickers', []):
            identity = bucket_id(account, mode, strategy['strategy_id'], ticker, strategy['version'], revision)
            if identity in existing:
                continue
            summary = dict(strategy=strategy['strategy_id'], name=strategy['display_name'], ticker=ticker,
                version=strategy['version'], revision=revision, status='awaiting approval',
                recommendation='INSUFFICIENT EVIDENCE', result_kind='hypothetical shadow',
                baseline='Native deployed policy; exact specification audit pending', candidates=[],
                pairs=0, sessions=0, required_pairs=None, required_sessions=None, coverage=None,
                last_collection=None, missing=['Approved frozen specifications', 'Verified decision evidence'],
                paper_policy=None, live_policy=None)
            publish(path, account, mode, summary, dict(rules={'baseline': summary['baseline']},
                candidates=[], history=[], exclusions=[], evidence=[], chart=[]))
            added += 1
    return added


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Publish Exit Lab preflight inventory outside HTTP requests')
    parser.add_argument('--user', required=True)
    args = parser.parse_args()
    print(json.dumps({'new_buckets': seed_inventory(args.user)}))
