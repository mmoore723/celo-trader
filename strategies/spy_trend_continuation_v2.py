"""Reviewed SPY Trend Continuation adapter.

This is intentionally a separate identity from the earlier TSLA experiment.
It rebuilds complete five-minute candles from live one-minute bars, matching
the paid SPY study: a signal at a completed five-minute close is eligible on
the following minute, and its reviewed exit is 90 minutes after entry.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from strategies.market_structure import Bar, TrendContinuation, TrendContinuationConfig, resample_regular_session
from strategies.base import Signal


STRATEGY_ID = "V2_SPY_TREND_CONT"
VALIDATED_TICKERS = frozenset({"SPY"})


def _complete_five_minute_bars(
    today: pd.DataFrame, now: object | None = None,
) -> tuple[Bar, ...]:
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(today.columns):
        return ()
    rows = today.sort_values("time").drop_duplicates("time")
    times = pd.to_datetime(rows["time"])
    # Live bar endpoints can include the currently forming minute.  The paid
    # study only used completed bars, so remove that minute before aggregation.
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    cutoff = cutoff.floor("min")
    rows = rows.loc[times < cutoff]
    one_minute = tuple(
        Bar(
            pd.Timestamp(row.time).to_pydatetime(), float(row.open),
            float(row.high), float(row.low), float(row.close),
            float(getattr(row, "volume", 0.0)),
        )
        for row in rows.itertuples(index=False)
    )
    # The resampler rejects an unfinished 5-minute bucket.  This protects the
    # live adapter from treating a forming bar as the closed bar used in study.
    return resample_regular_session(one_minute, source_minutes=1, target_minutes=5)


def evaluate(today: pd.DataFrame, ticker: str = "") -> Signal | None:
    if ticker.strip().upper() not in VALIDATED_TICKERS:
        return None
    bars = _complete_five_minute_bars(today)
    config = TrendContinuationConfig()
    minimum = max(config.slow_ema, config.atr_bars + 1, config.breakout_bars + 1)
    if len(bars) < minimum:
        return None
    candidate = TrendContinuation(config).evaluate(bars)
    if candidate is None:
        return None
    latest = today.iloc[-1]
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish" if candidate.side.value == "long" else "bearish",
        confidence=0.80,
        rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=pd.Timestamp(candidate.timestamp),
        meta={
            **candidate.features,
            "v2_hypothesis": "spy_trend_continuation_5m",
            "reviewed_paid_quote_rule": True,
            "entry_timing": "completed_5m_signal_then_next_1m_entry",
            "v2_entry_reference": float(candidate.entry_reference),
            "v2_stop": float(candidate.stop),
            "v2_target": float(candidate.target),
            "entry_bar_low": float(candidate.stop) if candidate.side.value == "long" else None,
            "entry_bar_high": float(candidate.stop) if candidate.side.value == "short" else None,
        },
    )
