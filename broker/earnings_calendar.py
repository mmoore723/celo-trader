"""Best-effort public earnings calendar, fetched outside the entry loop.

Only public ticker data is shared across accounts. No broker credentials or
account settings enter this worker. Expired results are never used as current.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

SOURCE = "Yahoo Finance via yfinance"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="earnings-calendar")
_lock = Lock()
_pending = {}
_cache = {}
_SUCCESS_TTL = 900
_FAILURE_TTL = 60
_MAX_PENDING = 32
_MAX_CACHE = 256


def _result(status, reason=None, dates=None):
    return dict(status=status, reason=reason, dates=dates, source=SOURCE,
                checked_at=datetime.now(timezone.utc).isoformat())


def fetch(symbol):
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        kind = ticker.get_info().get("quoteType")
        if kind in {"ETF", "MUTUALFUND", "INDEX"}:
            return _result("not_applicable", "Provider identifies a non-company instrument", [])
        if kind != "EQUITY":
            return _result("unavailable", "Instrument type could not be verified")
        calendar = ticker.get_calendar()
        upcoming = calendar.get("Earnings Date") if isinstance(calendar, dict) else None
        history = ticker.get_earnings_dates(limit=12)
        if not upcoming or history is None or history.empty:
            return _result("unavailable", "Upcoming or recent earnings dates missing")
        dates = {value.isoformat() for value in upcoming}
        for stamp in history.index:
            if stamp.tzinfo is None:
                return _result("unavailable", "Earnings timestamp has no timezone")
            dates.add(stamp.tz_convert("America/New_York").date().isoformat())
        from datetime import date
        dates = sorted(date.fromisoformat(value).isoformat() for value in dates)
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        if not dates or dates[0] > today or dates[-1] < today:
            return _result("unavailable", "Calendar does not span recent and upcoming earnings")
        return _result("available", dates=dates)
    except Exception as exc:
        # Do not log provider payloads, cookies or exception URLs.
        return _result("unavailable", f"Calendar request failed: {type(exc).__name__}")


def snapshot(symbol):
    """Return immediately; start bounded background refresh when required."""
    symbol = str(symbol).strip().upper()
    with _lock:
        now = monotonic()
        for key, future in list(_pending.items()):
            if future.done():
                try:
                    result = future.result()
                except Exception:
                    result = _result("unavailable", "Calendar worker failed")
                ttl = _SUCCESS_TTL if result["status"] in {"available", "not_applicable"} else _FAILURE_TTL
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(result["checked_at"])).total_seconds()
                _cache[key] = (now + max(0, ttl - max(0, age)), result)
                del _pending[key]
        while len(_cache) > _MAX_CACHE:
            del _cache[next(iter(_cache))]
        cached = _cache.get(symbol)
        if cached and now < cached[0]:
            return {**cached[1], "dates": list(cached[1]["dates"]) if cached[1]["dates"] is not None else None}
        if symbol not in _pending:
            if len(_pending) >= _MAX_PENDING:
                return _result("unavailable", "Calendar worker queue is full")
            _pending[symbol] = _pool.submit(fetch, symbol)
        return _result("loading", "Calendar refresh pending; no current verified result")
