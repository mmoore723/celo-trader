"""Approved experimental premarket eligibility, separate from entry/exit rules."""

from datetime import datetime, time, timedelta
import json
import math
import os
import tempfile
from threading import RLock
from hashlib import sha256

import pandas as pd

from scanner.premarket_volume import ET, matched_premarket_rvol

POLICY = "premarket_20261015_v1"
RULES = {
    "V2_TREND_CONT": (1.25, "hourly", 0),
    "V2_ORB_CONFIRMED_BREAKOUT": (1.50, "priority", 0),
    "V2_SPY_ORB_RSI_MACD_SHORT": (1.50, "hourly", 0),
    "V2_OPENING_MOMENTUM_RTH_EXPLORATORY": (1.50, "gap_hourly", "opening"),
    "V2_AFTERNOON_COMPRESSION_BREAKOUT": (1.0, "context", 0),
    "V2_MIDDAY_BREAKDOWN": (1.0, "priority", 0),
    "TV_SUPERTREND_REVERSAL_V4": (1.25, "context", 0),
    "V2_IMPULSE_ANCHORED_VWAP_PULLBACK": (1.25, "hourly", 0),
    "V2_VWAP_PULLBACK": (1.25, "hourly", 0),
    "V2_EMA_PULLBACK_RTH": (1.25, "ema15", 0),
    "V2_FAIR_VALUE_GAP": (1.25, "hourly", 0),
    "V2_GAP_FILL_RTH": (1.0, "context", .20),
    "V2_AFTERNOON_REVERSAL": (1.0, "context", 0),
    "V2_RANGE_SWEEP_RECLAIM": (1.0, "context", 0),
    "V2_TURTLE_SOUP_RTH": (1.0, "context", 0),
    "V2_VWAP_REVERSION_RTH": (1.0, "context", 0),
    "RESEARCH_CTX_ORB_ATR10_V2": (1.0, "atr10", 0),
    "RESEARCH_FAILED_RANGE_V2": (1.0, "context", 0),
}
_cache = {}
_locks = [RLock() for _ in range(64)]


def evaluate(strategy_id, ticker, direction, evidence):
    rule = RULES.get(strategy_id)
    if rule is None:
        return {"allowed": True, "applicable": False}
    minimum, alignment, gap_floor = rule
    reasons = []
    if evidence.get("data_error"):
        reasons.append("premarket_data_unavailable")
    rvol = evidence.get("rvol")
    if (evidence.get("premarket_volume_feed") != "tradier_consolidated"
            or not isinstance(rvol, (int, float)) or not math.isfinite(rvol)):
        reasons.append("premarket_volume_unavailable")
    elif rvol < minimum:
        reasons.append("premarket_rvol_below_minimum")
    side = {"bullish": "bullish", "long": "bullish", "bearish": "bearish", "short": "bearish"}.get(str(direction).lower())
    if side is None:
        reasons.append("unknown_direction")
    if gap_floor == "opening":
        gap_floor = .10 if ticker.upper() in {"SPY", "QQQ"} else .30
    gap = evidence.get("gap_pct")
    if gap_floor:
        if not isinstance(gap, (int, float)) or not math.isfinite(gap):
            reasons.append("premarket_gap_unavailable")
        elif abs(gap) + 1e-10 < gap_floor:
            reasons.append("premarket_gap_below_minimum")
        elif alignment == "gap_hourly" and ((gap > 0) != (side == "bullish")):
            reasons.append("gap_direction_mismatch")
    if alignment in {"hourly", "gap_hourly"} and evidence.get("hourly_direction") != side:
        reasons.append("hourly_alignment_missing_or_opposed")
    if alignment == "ema15" and evidence.get("ema15_direction") != side:
        reasons.append("ema15_alignment_missing_or_opposed")
    if alignment == "atr10" and evidence.get("atr10_pass") is not True:
        reasons.append("prior_daily_range_not_below_atr10_or_missing")
    return {"policy": POLICY, "applicable": True, "allowed": not reasons,
            "reasons": reasons, "minimum_rvol": minimum, "minimum_abs_gap_pct": gap_floor,
            "maximum_abs_gap_pct": None,
            "priority": alignment == "priority" and evidence.get("hourly_direction") == side,
            "evidence": evidence}


def _frame(client, ticker, timeframe, limit):
    from signals import bars_to_df
    rows, error = client.get_bars(ticker, timeframe, limit=limit)
    if error or not rows:
        return pd.DataFrame()
    frame = bars_to_df(rows)
    frame["time"] = pd.to_datetime(frame["time"])
    if frame["time"].dt.tz is not None:
        frame["time"] = frame["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    valid = frame[["open", "high", "low", "close", "volume"]].apply(
        lambda col: col.map(lambda value: math.isfinite(float(value)))).all(axis=1)
    valid &= (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid &= frame["volume"] >= 0
    frame = frame.loc[valid]
    return frame.sort_values("time").drop_duplicates("time", keep=False)


def _context(client, ticker, now, kind):
    from strategies.context_strategy_observers import _ema, _hourly
    from trading.research_ema_history import _native_bars
    cutoff = pd.Timestamp(datetime.combine(now.date(), time(9, 30)))
    result = {}
    if kind in {"hourly", "gap_hourly", "priority", "context"}:
        frame = _frame(client, ticker, "5Min", 1500)
        if not frame.empty:
            frame = frame.loc[frame["time"] + timedelta(minutes=5) <= cutoff]
            hours = _hourly(frame, cutoff)
            closes = [bar["close"] for bar in hours]
            if len(closes) >= 21:
                fast, slow, prior = _ema(closes, 10), _ema(closes, 20), _ema(closes[:-1], 20)
                result.update(hourly_ema10=fast, hourly_ema20=slow,
                              hourly_last_close=closes[-1], hourly_bar=hours[-1]["timestamp"].isoformat(),
                              hourly_direction="bullish" if closes[-1] > fast > slow > prior else
                              "bearish" if closes[-1] < fast < slow < prior else "neutral")
    if kind == "ema15":
        bars = _native_bars(_frame(client, ticker, "15Min", 1000), cutoff)
        if len(bars) >= 365:
            closes = [bar.close for bar in bars]
            fast, limit, trend = [_ema(closes, n) for n in (33, 165, 365)]
            result.update(ema15_fast=fast, ema15_limit=limit, ema15_trend=trend,
                          ema15_bar=bars[-1].timestamp.isoformat(),
                          ema15_direction="bullish" if fast > trend else "bearish" if fast < trend else "neutral")
    return result


def _daily(client, ticker, now):
    from strategies.context_strategy_observers import _atr10_gate
    frame = _frame(client, ticker, "1Day", 25)
    if frame.empty:
        return {}
    days = frame.loc[frame["time"].dt.date < now.date()].to_dict("records")
    if not days:
        return {}
    passed, detail = _atr10_gate(days)
    return {"prior_close": float(days[-1]["close"]), "prior_high": float(days[-1]["high"]),
            "prior_session": pd.Timestamp(days[-1]["time"]).date().isoformat(),
            "prior_low": float(days[-1]["low"]), "atr10_pass": passed, **detail}


def evidence_for(client, ticker, now, kind):
    from config.paths import get_user_data_dir
    now = now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)
    ticker = ticker.upper()
    if not ticker.isalnum():
        raise ValueError("Invalid underlying ticker")
    directory = get_user_data_dir() / "premarket_eligibility"
    bucket = min(now.strftime("%H:%M"), "09:30")
    key = (str(directory), now.date().isoformat(), ticker, bucket, kind)
    stripe = int.from_bytes(sha256(str(key).encode()).digest()[:2], "big") % len(_locks)
    with _locks[stripe]:
        cached = _cache.get(key)
        if cached and (now - cached[0]).total_seconds() < 60:
            return cached[1]
        path = directory / f"{now.date()}_{ticker}_{kind}.json"
        try:
            saved = json.loads(path.read_text())
            if saved["policy"] == POLICY and saved["bucket"] == bucket and saved["complete"]:
                return saved["evidence"]
        except (OSError, ValueError, KeyError):
            pass
        evidence = {"session": now.date().isoformat(), "cutoff_et": bucket,
                    "context_price_feed": "alpaca_iex", "context_asof": "prior_completed_rth"}
        try:
            evidence.update(matched_premarket_rvol(client, [ticker], now).get(ticker, {}))
        except Exception as exc:
            evidence["data_error"] = type(exc).__name__
        try:
            evidence.update(_daily(client, ticker, now))
            expected = evidence.get("premarket_history_end")
            if expected and evidence.get("prior_session") != expected:
                for field in ("prior_close", "prior_high", "prior_low", "atr10_pass"):
                    evidence.pop(field, None)
                evidence["daily_context_error"] = "stale_daily_context"
            if evidence.get("prior_close", 0) > 0 and evidence.get("premarket_close", 0) > 0:
                evidence["gap_pct"] = (evidence["premarket_close"] / evidence["prior_close"] - 1) * 100
        except Exception as exc:
            evidence["daily_context_error"] = type(exc).__name__
        try:
            evidence.update(_context(client, ticker, now, kind))
            expected = evidence.get("premarket_history_end")
            for field, direction in (("hourly_bar", "hourly_direction"), ("ema15_bar", "ema15_direction")):
                if expected and field in evidence and evidence[field][:10] != expected:
                    evidence.pop(direction, None)
        except Exception as exc:
            evidence["higher_timeframe_error"] = type(exc).__name__
        required = {"rvol", "premarket_close", "prior_close"}
        if kind in {"hourly", "gap_hourly"}:
            required.add("hourly_direction")
        if kind == "ema15":
            required.add("ema15_direction")
        if kind == "atr10":
            required.add("atr10_pass")
        complete = required <= evidence.keys() and "data_error" not in evidence
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump({"policy": POLICY, "bucket": bucket, "complete": complete,
                           "evidence": evidence}, handle, allow_nan=False)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if len(_cache) >= 512:
            _cache.clear()
        _cache[key] = (now, evidence)
        return evidence


def screen_signal(client, ticker, signal, now=None):
    rule = RULES.get(signal.strategy_id)
    if rule is None:
        return True
    now = now or datetime.now(ET)
    try:
        evidence = evidence_for(client, ticker, now, rule[1])
        result = evaluate(signal.strategy_id, ticker, signal.direction, evidence)
    except Exception as exc:
        result = {"policy": POLICY, "allowed": False, "reasons": ["premarket_data_unavailable"],
                  "data_error": type(exc).__name__}
    signal.meta = dict(signal.meta or {}, premarket_screen=result)
    return result["allowed"]
