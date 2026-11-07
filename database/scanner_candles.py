"""Persistent scanner-wide underlying candles for prospective research."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from database.connection import get_conn
from database.helpers import _to_et_isoformat


def record_scanner_candles(
    ticker: str,
    frame: pd.DataFrame,
    *,
    broker_account_id: str | None = None,
    timeframe: str = "1Min",
    source: str = "unknown",
    recorded_at: datetime | None = None,
) -> int:
    """Idempotently persist the bars available for one evaluated ticker."""
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return 0
    receipt = frame.attrs.get('received_at')
    try:
        receipt = datetime.fromisoformat(str(receipt).replace('Z', '+00:00')) if receipt else None
        if receipt is not None and receipt.tzinfo is None:
            receipt = None
    except ValueError:
        receipt = None
    now_text = _to_et_isoformat(recorded_at or receipt or datetime.now(timezone.utc))
    source = str(frame.attrs.get('data_feed') or source)
    rows = []
    for row in frame.sort_values("time").drop_duplicates("time", keep="last").itertuples(index=False):
        rows.append((
            str(broker_account_id or ""), ticker.strip().upper(), timeframe,
            _to_et_isoformat(pd.Timestamp(row.time).to_pydatetime()),
            float(row.open), float(row.high), float(row.low), float(row.close),
            float(getattr(row, "volume", 0.0) or 0.0), source, now_text,
        ))
    with get_conn() as conn:
        # Preserve every distinct revision and its first receipt, including the
        # prior canonical value before an upsert changes its feed or prices.
        conn.execute('''CREATE TABLE IF NOT EXISTS scanner_candle_versions (
            broker_account_id TEXT NOT NULL, ticker TEXT NOT NULL, timeframe TEXT NOT NULL,
            bar_time TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
            volume REAL, source TEXT NOT NULL, recorded_at TEXT NOT NULL,
            UNIQUE(broker_account_id,ticker,timeframe,bar_time,source,open,high,low,close,volume))''')
        conn.executemany('''INSERT OR IGNORE INTO scanner_candle_versions
            SELECT broker_account_id,ticker,timeframe,bar_time,open,high,low,close,volume,source,recorded_at
            FROM scanner_candle_observations
            WHERE broker_account_id=? AND ticker=? AND timeframe=? AND bar_time=?''',
            [row[:4] for row in rows])
        conn.executemany('''INSERT OR IGNORE INTO scanner_candle_versions
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''', rows)
        before = conn.total_changes
        conn.executemany(
            """INSERT INTO scanner_candle_observations
               (broker_account_id,ticker,timeframe,bar_time,open,high,low,close,volume,source,recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(broker_account_id,ticker,timeframe,bar_time) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 source=excluded.source, recorded_at=excluded.recorded_at""",
            rows,
        )
        return conn.total_changes - before


def load_scanner_candles(
    ticker: str,
    *,
    broker_account_id: str | None = None,
    timeframe: str = "1Min",
    limit: int = 10_000,
    required_source: str | None = None,
) -> pd.DataFrame:
    """Load one account's most recent canonical scanner bars, oldest first."""
    if limit < 1:
        raise ValueError("limit must be positive")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT bar_time,open,high,low,close,volume,source,recorded_at
               FROM (
                 SELECT bar_time,open,high,low,close,volume,source,recorded_at
                 FROM scanner_candle_observations
                 WHERE broker_account_id=? AND ticker=? AND timeframe=?
                   AND (? IS NULL OR source=?)
                 ORDER BY bar_time DESC LIMIT ?
               ) ORDER BY bar_time""",
            (str(broker_account_id or ""), ticker.strip().upper(), timeframe,
             required_source, required_source, limit),
        ).fetchall()
    result = pd.DataFrame.from_records(
        rows, columns=("time", "open", "high", "low", "close", "volume", "source", "recorded_at"),
    )
    sources = set(result['source'])
    result.attrs['data_feed'] = next(iter(sources)) if len(sources) == 1 else 'mixed_or_missing'
    result.attrs['received_at'] = str(result['recorded_at'].max()) if not result.empty else None
    result = result.drop(columns=['source', 'recorded_at'])
    return result
