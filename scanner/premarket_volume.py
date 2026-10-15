"""Matched-window premarket volume, without daily-volume substitutes."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import math

ET = ZoneInfo("America/New_York")
HISTORY_SESSIONS = 20
MIN_PREMARKET_RVOL = 1.0


def window_volume(bars, session, cutoff):
    start = datetime.combine(session, time(4), ET)
    end = datetime.combine(session, cutoff, ET)
    seen = {}
    for bar in bars:
        stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Premarket timestamps must include timezone")
        stamp = stamp.astimezone(ET)
        if start <= stamp and stamp + timedelta(minutes=1) <= end:
            volume = float(bar["v"])
            if not math.isfinite(volume) or volume < 0:
                raise ValueError("Invalid premarket volume")
            seen[stamp] = volume
    return sum(seen.values()) if seen else None


def matched_premarket_rvol(alpaca, symbols, now):
    now = now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)
    cutoff = min(now.time().replace(second=0, microsecond=0, tzinfo=None), time(9, 30))
    if cutoff <= time(4) or not symbols:
        return {}
    calendar = alpaca._get(f"{alpaca.base}/v2/calendar", {
        "start": (now.date() - timedelta(days=60)).isoformat(),
        "end": now.date().isoformat(),
    })
    prior = sorted({datetime.fromisoformat(row["date"]).date()
                    for row in calendar if row["date"] < now.date().isoformat()})[-HISTORY_SESSIONS:]
    if len(prior) != HISTORY_SESSIONS:
        return {}
    volumes = {symbol: [] for symbol in symbols}
    for session in prior + [now.date()]:
        params = {
            "symbols": ",".join(symbols), "timeframe": "1Min", "feed": "iex",
            "adjustment": "raw", "limit": 10000, "sort": "asc",
            "start": datetime.combine(session, time(4), ET).isoformat(),
            "end": datetime.combine(session, cutoff, ET).isoformat(),
        }
        collected = {symbol: [] for symbol in symbols}
        tokens = set()
        for _ in range(100):
            payload = alpaca._get(f"{alpaca.data}/v2/stocks/bars", params)
            for symbol, bars in (payload.get("bars") or {}).items():
                if symbol in collected:
                    collected[symbol].extend(bars or [])
            token = payload.get("next_page_token")
            if not token:
                break
            if token in tokens:
                raise ValueError("Repeated premarket pagination token")
            tokens.add(token)
            params = dict(params, page_token=token)
        else:
            raise ValueError("Incomplete premarket pagination")
        for symbol in symbols:
            volumes[symbol].append(window_volume(collected[symbol], session, cutoff))
    results = {}
    for symbol, values in volumes.items():
        if any(value is None for value in values):
            continue
        average = sum(values[:-1]) / HISTORY_SESSIONS
        if average <= 0:
            continue
        results[symbol] = {
            "rvol": values[-1] / average,
            "premarket_volume": values[-1], "premarket_average_volume": average,
            "premarket_history_sessions": HISTORY_SESSIONS,
            "premarket_window": f"04:00-{cutoff:%H:%M} America/New_York",
            "premarket_volume_feed": "iex",
        }
    return results
