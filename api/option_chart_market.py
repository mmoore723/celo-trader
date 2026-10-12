"""Read-only exact-contract chart data, separate from execution pricing."""
from datetime import datetime
import math
import re
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def daily_option_candles(client, symbol, start, end):
    symbol = str(symbol).replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z0-9.]{1,6}\d{6}[CP]\d{8}", symbol):
        raise ValueError("Full OCC symbol required")
    payload = client._get("/markets/history", {
        "symbol": symbol, "interval": "daily",
        "start": start.astimezone(ET).date().isoformat(),
        "end": end.astimezone(ET).date().isoformat(),
    })
    rows = (payload.get("history") or {}).get("day") or []
    rows = [rows] if isinstance(rows, dict) else rows
    candles = {}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(row["date"]).replace(tzinfo=ET).timestamp()
            o, h, l, c = (float(row[key]) for key in ("open", "high", "low", "close"))
            v = float(row.get("volume") or 0)
            if not all(math.isfinite(x) and x >= 0 for x in (o, h, l, c, v)):
                continue
            if h < max(o, l, c) or l > min(o, h, c):
                continue
            candles[stamp] = dict(time=stamp, open=o, high=h, low=l, close=c, volume=int(v))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [candles[key] for key in sorted(candles)]


def current_option_bid(client, symbol, now):
    quote = client.get_option_quote(symbol)
    if not quote or quote.get("source_symbol") != symbol:
        return None
    try:
        bid, ask = float(quote["bid"]), float(quote["ask"])
        stamp = float(quote["bid_date"]) / 1000
        if not all(math.isfinite(x) for x in (bid, ask, stamp)):
            return None
        if bid < 0 or ask <= 0 or ask < bid or not 0 < stamp <= now:
            return None
        return dict(time=stamp, bid=bid, ask=ask)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
