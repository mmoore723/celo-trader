"""Read-only, account-scoped option chart evidence. Never used to price orders."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo("America/New_York"))
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def read_option_chart(path: Path, *, trade_id: int, account_id: str,
                      paper: bool, now: datetime | None = None) -> dict | None:
    """Fail closed on identity/mode; return actual observations, never OHLC proxies."""
    if not account_id or not path.is_file():
        return None
    now_s = (now or datetime.now(timezone.utc)).timestamp()
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM trades WHERE id=? AND broker_account_id=? AND paper=?",
            (trade_id, account_id, int(paper)),
        ).fetchone()
        if row is None:
            return None
        trade = dict(row)
        start = _time(trade.get("entry_fill_time") or trade.get("entry_time"))
        end = _time(trade.get("exit_fill_time") or trade.get("exit_time"))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        observations = []
        if "option_quote_observations" in tables:
            observations = conn.execute(
                """SELECT observed_at, bid, ask, source FROM option_quote_observations
                   WHERE trade_id=? AND contract_symbol=? ORDER BY observed_at DESC, id DESC LIMIT 5001""",
                (trade_id, trade["contract_symbol"]),
            ).fetchall()
        points = {}
        for quote in observations[:5000]:
            stamp, bid, ask = _time(quote["observed_at"]), _number(quote["bid"]), _number(quote["ask"])
            if (start is None or stamp is None or stamp < start or stamp > min(end or now_s, now_s)
                    or bid is None or ask is None or bid < 0 or ask <= 0 or ask < bid
                    or quote["source"] not in {"tradier_quote", "tradier_chain", "tradier_pre_submit_exit_quote"}):
                continue
            points.setdefault(stamp, {"time": stamp, "bid": bid, "ask": ask})
        return {
            "trade_id": trade_id, "mode": "paper" if paper else "live",
            "ticker": trade["ticker"], "contract_symbol": trade["contract_symbol"],
            "option_type": trade["option_type"], "strike": _number(trade.get("strike")),
            "expiry": trade.get("expiry"), "contracts": int(trade["contracts"]),
            "entry_price": _number(trade["entry_price"]), "entry_time": start,
            "exit_price": _number(trade.get("exit_price")), "exit_time": end,
            "realized_pnl": _number(trade.get("realized_pnl")),
            "stop_price": _number(trade.get("stop_price")),
            "target_price": _number(trade.get("target_price")),
            "closed": trade.get("status") == "closed" or end is not None,
            "candles": [],
            "candle_source": None,
            "quotes": [points[key] for key in sorted(points)],
            "truncated": len(observations) > 5000,
            "as_of": now_s,
        }
    finally:
        conn.close()
