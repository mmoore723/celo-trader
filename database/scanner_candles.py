"""Persistent scanner-wide underlying candles for prospective research."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from database.connection import get_conn
from database.helpers import _to_et_isoformat


def record_scanner_candles(
    ticker: str,
    frame: pd.DataFrame,
    *,
    broker_account_id: str | None = None,
    timeframe: str = "1Min",
    source: str = "alpaca",
    recorded_at: datetime | None = None,
) -> int:
    """Idempotently persist the bars available for one evaluated ticker."""
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return 0
    now_text = _to_et_isoformat(recorded_at or datetime.now())
    rows = []
    for row in frame.sort_values("time").drop_duplicates("time", keep="last").itertuples(index=False):
        rows.append((
            str(broker_account_id or ""), ticker.strip().upper(), timeframe,
            _to_et_isoformat(pd.Timestamp(row.time).to_pydatetime()),
            float(row.open), float(row.high), float(row.low), float(row.close),
            float(getattr(row, "volume", 0.0) or 0.0), source, now_text,
        ))
    with get_conn() as conn:
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
