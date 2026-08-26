"""Causal strategy replay over every ticker present in the event tape."""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pandas as pd

from config.strategy_catalog import REVIEWED_STRATEGIES


def _minute(value: object) -> str | None:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("America/New_York")
    return stamp.tz_convert("UTC").floor("min").isoformat()


def _key(strategy_id: str, ticker: str, direction: str, trigger: object) -> tuple | None:
    minute = _minute(trigger)
    return (strategy_id, ticker, direction, minute) if minute else None


def _frames(events: list[dict]) -> dict[str, pd.DataFrame]:
    rows: dict[str, list[dict]] = {}
    for event in events:
        if event["kind"] != "market_bar" or event["payload"].get("timeframe") != "1Min":
            continue
        payload = event["payload"]
        stamp = pd.Timestamp(payload["bar_time"])
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("America/New_York").tz_localize(None)
        rows.setdefault(str(event["ticker"]).upper(), []).append({
            "time": stamp, "open": payload["open"],
            "high": payload["high"], "low": payload["low"], "close": payload["close"],
            "volume": payload.get("volume", 0), "rvol": 0.0,
        })
    return {ticker: pd.DataFrame(values).sort_values("time").drop_duplicates("time")
            for ticker, values in rows.items()}


def _bar_signals(strategy_id: str, ticker: str, frame: pd.DataFrame, scope: str) -> set[tuple]:
    from trading.cross_ticker_shadow import evaluate_bar_strategy
    if strategy_id == "V2_SPY_TREND_CONT":
        from strategies.spy_trend_continuation_v2 import evaluate
    elif strategy_id == "V2_SPY_AFTERNOON_FVG":
        from strategies.spy_afternoon_fvg_v2 import evaluate
    else:
        from strategies.spy_failed_range_recovery_v2 import evaluate
    found = set()
    for end in range(1, len(frame) + 1):
        signal = evaluate_bar_strategy(
            strategy_id, evaluate, frame.iloc[:end], ticker=ticker, account_scope=scope,
        )
        if signal:
            found.add(_key(strategy_id, ticker, signal.direction, signal.trigger_bar))
    return {item for item in found if item is not None}


def _two_leg_signals(strategy_id: str, ticker: str, frame: pd.DataFrame) -> set[tuple]:
    from trading.cross_ticker_shadow import update_two_leg
    state: dict = {}
    found = set()
    for end in range(1, len(frame) + 1):
        now = pd.Timestamp(frame.iloc[end - 1]["time"]).to_pydatetime() + timedelta(minutes=1)
        signal, _ = update_two_leg(state, frame.iloc[:end], ticker=ticker, now=now)
        if signal:
            found.add(_key(strategy_id, ticker, signal.direction, signal.trigger_bar))
    return {item for item in found if item is not None}


def _orb_signals(strategy_id: str, ticker: str, frame: pd.DataFrame,
                 quotes: list[dict]) -> set[tuple]:
    from trading.cross_ticker_shadow import update_orb
    state: dict = {}
    found = set()
    for event in quotes:
        now = pd.Timestamp(event["timestamp"]).to_pydatetime()
        signal, _ = update_orb(
            state, frame, ticker=ticker, quote_price=float(event["payload"]["mid"]), now=now,
        )
        if signal:
            found.add(_key(strategy_id, ticker, signal.direction, signal.trigger_bar))
    return {item for item in found if item is not None}


def _cleanup_scope(scope: str) -> None:
    from strategies import spy_afternoon_fvg_v2 as fvg
    from strategies import spy_failed_range_recovery_v2 as failed
    from strategies import spy_trend_continuation_v2 as trend
    owns = lambda key: scope in str(key[0])
    trend._emitted_trigger_by_session = {
        key: value for key, value in trend._emitted_trigger_by_session.items() if not owns(key)
    }
    trend._active_breakout_by_session = {
        key: value for key, value in trend._active_breakout_by_session.items() if not owns(key)
    }
    fvg._emitted_trigger_by_session = {
        key for key in fvg._emitted_trigger_by_session if not owns(key)
    }
    failed._emitted_trigger_by_session = {
        key: value for key, value in failed._emitted_trigger_by_session.items() if not owns(key)
    }


def replay_strategies(events: list[dict]) -> dict:
    """Re-run every reviewed rule on every ticker the scanner preserved."""
    frames = _frames(events)
    actual: set[tuple] = set()
    malformed = 0
    for event in events:
        if event["kind"] != "candidate" or event.get("strategy_id") not in REVIEWED_STRATEGIES:
            continue
        payload = event["payload"]
        item = _key(event["strategy_id"], str(event["ticker"]).upper(),
                    str(payload.get("direction")), payload.get("trigger_bar"))
        if item: actual.add(item)
        else: malformed += 1
    quote_by_ticker: dict[str, list[dict]] = {}
    for event in events:
        if event["kind"] == "underlying_quote":
            quote_by_ticker.setdefault(str(event["ticker"]).upper(), []).append(event)
    scope = f"golden:{uuid4().hex}"
    checks = []
    try:
        for ticker, frame in frames.items():
            for strategy_id, rule in REVIEWED_STRATEGIES.items():
                pair_actual = {item for item in actual if item[0] == strategy_id and item[1] == ticker}
                if rule.signal_source == "live_retouch" and not quote_by_ticker.get(ticker):
                    checks.append({"strategy_id": strategy_id, "ticker": ticker,
                                   "status": "missing_underlying_quote_tape",
                                   "replayed": 0, "recorded": len(pair_actual)})
                    continue
                if rule.signal_source == "live_retouch":
                    expected = _orb_signals(strategy_id, ticker, frame, quote_by_ticker[ticker])
                elif rule.signal_source == "one_minute_state":
                    expected = _two_leg_signals(strategy_id, ticker, frame)
                else:
                    expected = _bar_signals(strategy_id, ticker, frame, scope)
                checks.append({
                    "strategy_id": strategy_id, "ticker": ticker,
                    "status": "passed" if expected == pair_actual else "mismatch",
                    "replayed": len(expected), "recorded": len(pair_actual),
                    "missing_recorded_candidates": len(expected - pair_actual),
                    "unreproduced_recorded_candidates": len(pair_actual - expected),
                })
    finally:
        _cleanup_scope(scope)
    comparable = [check for check in checks if check["status"] != "missing_underlying_quote_tape"]
    return {
        "complete": bool(checks) and len(comparable) == len(checks),
        "passed": bool(comparable) and all(check["status"] == "passed" for check in comparable),
        "tickers_replayed": sorted(frames), "strategy_ticker_checks": checks,
        "malformed_recorded_candidates": malformed,
    }
