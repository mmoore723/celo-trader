"""Matched-window premarket volume, without daily-volume substitutes."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import math
import logging
import time as clock

ET = ZoneInfo("America/New_York")
HISTORY_DAYS = 10
MIN_PREMARKET_RVOL = 1.0
logger = logging.getLogger("celo_trader.scanner")


def _market_client():
    from config import get_api_keys
    from broker.tradier_client import TradierClient
    keys = get_api_keys()
    token = keys.get("tradier_market_api_key") or keys.get("tradier_api_key")
    if not token:
        raise ValueError("Tradier production market-data token required")
    return TradierClient(api_key=token, base_url="https://api.tradier.com/v1")


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


def matched_premarket_rvol(alpaca, symbols, now, *, tradier=None):
    now = now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)
    cutoff = min(now.time().replace(second=0, microsecond=0, tzinfo=None), time(9, 30))
    if cutoff <= time(4) or not symbols:
        return {}
    start_date = now.date() - timedelta(days=HISTORY_DAYS - 1)
    params = {
        "start": start_date.isoformat(),
        "end": now.date().isoformat(),
    }
    calendar_reader = getattr(alpaca, "premarket_calendar", None)
    calendar = (calendar_reader(params) if callable(calendar_reader)
                else alpaca._get(f"{alpaca.base}/v2/calendar", params))
    prior = sorted({datetime.fromisoformat(row["date"]).date()
                    for row in calendar
                    if start_date.isoformat() <= row["date"] < now.date().isoformat()})
    if not prior:
        return {}
    client = tradier if tradier is not None else _market_client()
    if client.base.rstrip("/") != "https://api.tradier.com/v1":
        raise ValueError("Delayed Tradier sandbox data cannot supply premarket RVOL")
    results = {}
    last_request = None
    for symbol in dict.fromkeys(symbols):
        if last_request is not None:
            clock.sleep(max(0.0, 0.65 - (clock.monotonic() - last_request)))
        last_request = clock.monotonic()
        try:
            payload = client._get("/markets/timesales", {
                "symbol": symbol, "interval": "1min", "session_filter": "all",
                "start": f"{start_date} 04:00", "end": f"{now.date()} {cutoff:%H:%M}",
            })
            series = payload.get("series") or {}
            raw = series.get("data") or [] if isinstance(series, dict) else []
            raw = [raw] if isinstance(raw, dict) else raw
            bars = []
            for row in raw:
                stamp = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=ET)
                bars.append({"t": stamp.isoformat(), "v": row["volume"],
                             **{k: row.get(k) for k in ("open", "high", "low", "close")}})
            values = [window_volume(bars, session, cutoff) for session in prior + [now.date()]]
        except Exception as ex:
            logger.warning("Consolidated premarket RVOL unavailable for %s: %s", symbol, ex)
            continue
        if any(value is None for value in values):
            continue
        average = sum(values[:-1]) / len(prior)
        if average <= 0:
            continue
        results[symbol] = {
            "rvol": values[-1] / average,
            "premarket_volume": values[-1], "premarket_average_volume": average,
            "premarket_history_sessions": len(prior),
            "premarket_history_days": HISTORY_DAYS,
            "premarket_history_start": prior[0].isoformat(),
            "premarket_history_end": prior[-1].isoformat(),
            "premarket_window": f"04:00-{cutoff:%H:%M} America/New_York",
            "premarket_volume_feed": "tradier_consolidated",
        }
        end = datetime.combine(now.date(), cutoff, ET)
        current = sorted((bar for bar in bars
                          if datetime.combine(now.date(), time(4), ET)
                          <= datetime.fromisoformat(bar["t"])
                          and datetime.fromisoformat(bar["t"]) + timedelta(minutes=1) <= end),
                         key=lambda bar: bar["t"])
        try:
            prices_valid = bool(current) and all(
                all(bar.get(k) is not None and math.isfinite(float(bar[k])) and float(bar[k]) > 0
                    for k in ("high", "low", "close"))
                and float(bar["low"]) <= float(bar["close"]) <= float(bar["high"])
                for bar in current)
        except (TypeError, ValueError, OverflowError):
            prices_valid = False
        if prices_valid:
            results[symbol].update(
                premarket_close=float(current[-1]["close"]),
                premarket_high=max(float(bar["high"]) for bar in current),
                premarket_low=min(float(bar["low"]) for bar in current),
            )
    return results
