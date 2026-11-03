"""Research-only gap recovery with receipt-time provenance, never synthetic bars."""
import json
import logging
from collections import OrderedDict
from threading import RLock
from datetime import timedelta

import pandas as pd
from signals import bars_to_df
from strategy_health.impulse_exit import et

logger = logging.getLogger('celo_trader.research')
_complete = OrderedDict()
_cache_lock = RLock()


def validated_frame(bars, now):
    """Reject corrupt bars and exclude forming candles before reuse."""
    import numpy as np
    frame = bars_to_df(bars)
    missing_minutes(frame, now)  # reject duplicates before filtering
    cutoff = et(now).replace(second=0, microsecond=0)
    stamps = frame['time'].map(et)
    frame = frame.loc[(stamps.dt.date == cutoff.date()) & (stamps < cutoff)].copy()
    values = frame[['open', 'high', 'low', 'close']].astype(float)
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
        raise ValueError('Invalid session OHLC')
    if not ((values.low <= values[['open','close']].min(axis=1)) &
            (values.high >= values[['open','close']].max(axis=1))).all():
        raise ValueError('Inconsistent session OHLC')
    return frame


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
             fallback.attrs.get('source', 'tradier_session_1m_recovery_v1'), json.dumps([str(x) for x in missing]),
             int(accepted), error, payload))


def session_frame(primary, fallback, ticker, *, account, clock, persist=record_recovery,
                  prefer_consolidated=True):
    """Accept a valid complete frame or a strictly better coverage superset.

    Never merge feeds, manufacture bars, or remove a minute present in primary.
    Partial recovery is not completion: downstream policy gap checks still apply.
    """
    now = clock()
    from config import get_db_path
    cache_key = (str(get_db_path()), account, ticker.upper(), et(now).replace(second=0,microsecond=0))
    if prefer_consolidated and et(now).hour >= 9 and et(now).time() >= et(now).replace(hour=9,minute=31,second=0,microsecond=0).time():
        with _cache_lock:
            cached = _complete.get(cache_key)
            if cached is not None:
                return cached.copy(deep=True)
        try:
            bars, error, _ = fallback.get_session_bars(ticker, '1Min')
            if error or not bars:
                raise ValueError('Consolidated request failed or returned no bars')
            direct = validated_frame(bars, now)
            gaps = missing_minutes(direct, now)
            if gaps:
                raise ValueError(f'Consolidated session missing {len(gaps)} completed minutes')
            received = clock()
            direct.attrs.update(source='tradier_session_1m_direct_v2', coverage_complete=True,
                                missing_minutes=[], received_at=str(received))
            persist(ticker=ticker, account=account, now=now, received=received,
                    missing=[], fallback=direct, accepted=True, error=None)
            with _cache_lock:
                _complete[cache_key] = direct.copy(deep=True)
                while len(_complete) > 128:
                    _complete.popitem(last=False)
            logger.debug('research_bar_capture ticker=%s source=tradier completed_minutes=%d missing_minutes=0', ticker, len(direct))
            return direct
        except Exception as exc:
            logger.warning('research_bar_capture ticker=%s preferred_source=tradier failure=%s; checking alternate feed', ticker, exc)
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
        remaining = missing_minutes(replacement, now)
        if not set(remaining) < set(missing):
            raise ValueError('Fallback does not strictly improve completed-minute coverage')
        values = replacement[['open', 'high', 'low', 'close']].astype(float)
        import numpy as np
        if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
            raise ValueError('Invalid fallback OHLC')
        if not ((values.low <= values[['open', 'close']].min(axis=1)) &
                (values.high >= values[['open', 'close']].max(axis=1))).all():
            raise ValueError('Inconsistent fallback OHLC')
        accepted = True
        replacement.attrs.update(
            source=('tradier_session_1m_partial_recovery_v1' if remaining
                    else 'tradier_session_1m_recovery_v1'),
            coverage_complete=not remaining,
            missing_minutes=[str(x) for x in remaining])
    except Exception as exc:
        failure = str(exc)
    received = clock()
    persist(ticker=ticker, account=account, now=now, received=received,
            missing=missing, fallback=replacement, accepted=accepted, error=failure)
    logger.info('research_bar_recovery ticker=%s missing_minutes=%d accepted=%s remaining_minutes=%s error=%s',
                ticker, len(missing), accepted,
                len(replacement.attrs.get('missing_minutes', [])) if accepted else 'unknown', failure)
    if accepted:
        replacement.attrs.update(received_at=str(received))
        return replacement
    return frame
