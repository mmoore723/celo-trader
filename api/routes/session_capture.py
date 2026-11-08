"""Persisted market-capture coverage. No collection or analysis on requests."""
import json
import sqlite3
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from config.paths import get_user_data_dir

router = APIRouter(prefix='/api/session-capture', tags=['research'])


@router.get('')
def coverage():
    path = get_user_data_dir(create=False) / 'session_capture_health.json'
    try:
        data = json.loads(path.read_text())
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(data['heartbeat_at'])).total_seconds()
        data['worker_stale'] = age > 90
        data['heartbeat_age_seconds'] = round(age,1)
        return data
    except (OSError, ValueError, KeyError):
        return dict(status='not_verified',tickers=[],worker_stale=True,
                    error='No saved full-session coverage report is available.')


@router.get('/contracts')
def contracts(ticker: str = Query(pattern=r'^[A-Z][A-Z0-9.-]{0,11}$'),
              day: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'),
              page: int = Query(1,ge=1,le=100000)):
    path = get_user_data_dir(create=False) / 'session_capture' / 'session_capture.sqlite3'
    if not path.exists():
        return dict(rows=[],has_more=False)
    conn = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)
    conn.row_factory=sqlite3.Row
    try:
        rows=conn.execute('''SELECT symbol,expiration,first_seen,last_seen,last_quote,validation
            FROM contracts WHERE ticker=? AND day=? ORDER BY symbol LIMIT 101 OFFSET ?''',
            (ticker,day,(page-1)*100)).fetchall()
        return dict(rows=[dict(r) for r in rows[:100]],has_more=len(rows)>100)
    finally:
        conn.close()
