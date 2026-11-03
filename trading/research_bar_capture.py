"""Research-only gap recovery with receipt-time provenance, never synthetic bars."""
import json
import logging
from datetime import timedelta

import pandas as pd
from signals import bars_to_df
from strategy_health.impulse_exit import et

logger = logging.getLogger('celo_trader.research')


def missing_minutes(frame, now):
    now = et(now).replace(second=0, microsecond=0)
    start = now.replace(hour=9, minute=30)
    end = min(now, now.replace(hour=16, minute=0))
    expected = set()
    while start < end:
        expected.add(start)
        start += timedelta(minutes=1)
    stamps = [et(value) for value in frame.get('time', [])]
    if len(stamps) != len(set(stamps)):
        raise ValueError('Duplicate research minute bars')
    return sorted(expected - set(stamps))


def record_recovery(*, ticker, account, now, received, missing, fallback, accepted, error):
    """Append new evidence; never overwrite historical candles or failed tests."""
    from database.connection import get_conn
    payload = json.dumps(fallback.to_dict('records'), default=str)
    with get_conn() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS research_bar_recoveries (
            id INTEGER PRIMARY KEY, broker_account_id TEXT, ticker TEXT NOT NULL,
            requested_at TEXT NOT NULL, received_at TEXT NOT NULL,
            source TEXT NOT NULL, missing_primary_json TEXT NOT NULL,
            accepted INTEGER NOT NULL, error TEXT, bars_json TEXT NOT NULL)''')
        conn.execute('''INSERT INTO research_bar_recoveries
            (broker_account_id,ticker,requested_at,received_at,source,
             missing_primary_json,accepted,error,bars_json) VALUES (?,?,?,?,?,?,?,?,?)''',
            (account, ticker, et(now).isoformat(), et(received).isoformat(),
             'tradier_session_1m_recovery_v1', json.dumps([str(x) for x in missing]),
             int(accepted), error, payload))


def session_frame(primary, fallback, ticker, *, account, clock, persist=record_recovery):
    """One fallback read per lookup; only a complete, valid same-session frame wins."""
    now = clock()
    try:
        bars, error, _ = primary.get_session_bars(ticker, '1Min')
        frame = bars_to_df(bars) if bars and not error else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    try:
        missing = missing_minutes(frame, now)
    except ValueError:
        missing = missing_minutes(pd.DataFrame(), now)
    if not missing:
        return frame
    replacement, accepted, failure = pd.DataFrame(), False, None
    try:
        bars, error, _ = fallback.get_session_bars(ticker, '1Min')
        if error or not bars:
            raise ValueError('Fallback request failed or returned no bars')
        replacement = bars_to_df(bars)
        if missing_minutes(replacement, now):
            raise ValueError('Fallback still lacks completed session minutes')
        values = replacement[['open', 'high', 'low', 'close']].astype(float)
        import numpy as np
        if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
            raise ValueError('Invalid fallback OHLC')
        if not ((values.low <= values[['open', 'close']].min(axis=1)) &
                (values.high >= values[['open', 'close']].max(axis=1))).all():
            raise ValueError('Inconsistent fallback OHLC')
        accepted = True
    except Exception as exc:
        failure = str(exc)
    received = clock()
    persist(ticker=ticker, account=account, now=now, received=received,
            missing=missing, fallback=replacement, accepted=accepted, error=failure)
    logger.info('research_bar_recovery ticker=%s missing_minutes=%d accepted=%s error=%s',
                ticker, len(missing), accepted, failure)
    if accepted:
        replacement.attrs.update(source='tradier_session_1m_recovery_v1', received_at=str(received))
        return replacement
    return frame
