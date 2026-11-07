"""Tradier market clock, equity quotes, and normalized OHLCV bars."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, time as wall_time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo
from broker.shared_market import FEED_POLICY, stamp_bars

logger = logging.getLogger("celo_trader.broker")
ET = ZoneInfo("America/New_York")


def _objects(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return [value] if isinstance(value, dict) else []


def _quote_age_seconds(quote: dict) -> float | None:
    epoch_ms = max(
        float(quote.get(key) or 0)
        for key in ("bid_date", "ask_date", "trade_date")
    )
    if epoch_ms <= 0:
        return None
    epoch_seconds = epoch_ms / 1000 if epoch_ms > 10_000_000_000 else epoch_ms
    return max(0.0, time.time() - epoch_seconds)


def _utc_bar_time(value: object) -> str:
    """Normalize Tradier's timezone-naive Eastern timestamps to UTC ISO."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _quote_timestamp(raw):
    stamp = max(float(raw.get('bid_date') or 0), float(raw.get('ask_date') or 0))
    if stamp <= 0:
        return None
    seconds = stamp / 1000 if stamp > 10_000_000_000 else stamp
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _bar(row: dict) -> dict | None:
    stamp = row.get("time") or row.get("date")
    if not stamp:
        return None
    try:
        return {
            "t": _utc_bar_time(stamp),
            "o": float(row.get("open") or row.get("price") or 0),
            "h": float(row.get("high") or row.get("price") or 0),
            "l": float(row.get("low") or row.get("price") or 0),
            "c": float(row.get("close") or row.get("price") or 0),
            "v": int(float(row.get("volume") or 0)),
            "vw": float(row.get("vwap") or 0),
        }
    except (TypeError, ValueError):
        return None


def _hourly(rows: list[dict]) -> list[dict]:
    """Aggregate normalized 15-minute bars into 9:30-anchored hourly bars."""
    groups: dict[tuple[date, int], list[dict]] = defaultdict(list)
    for row in rows:
        stamp = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00")).astimezone(ET)
        minutes = stamp.hour * 60 + stamp.minute - (9 * 60 + 30)
        if minutes < 0:
            continue
        groups[(stamp.date(), minutes // 60)].append(row)
    result = []
    for key in sorted(groups):
        values = sorted(groups[key], key=lambda item: item["t"])
        volume = sum(int(item.get("v") or 0) for item in values)
        result.append({
            "t": values[0]["t"], "o": values[0]["o"],
            "h": max(item["h"] for item in values),
            "l": min(item["l"] for item in values),
            "c": values[-1]["c"], "v": volume,
            "vw": (
                sum(float(item.get("vw") or item["c"]) * int(item.get("v") or 0) for item in values) / volume
                if volume else values[-1]["c"]
            ),
        })
    return result


class TradierMarketMixin:
    """Alpaca-compatible market-data surface backed only by Tradier."""

    def is_market_open(self) -> bool:
        try:
            payload = self._get("/markets/clock")
            return str((payload.get("clock") or {}).get("state") or "").lower() == "open"
        except Exception:
            logger.warning("tradier market clock unavailable", exc_info=True)
            return False

    def _quote_rows(self, symbols: list[str]) -> list[dict]:
        if (not symbols or not getattr(self, "api_key", "")
                or getattr(self, "base", "") != "https://api.tradier.com/v1"):
            return []
        payload = self._get("/markets/quotes", {
            "symbols": ",".join(symbols), "greeks": "false",
        })
        return _objects((payload.get("quotes") or {}).get("quote"))

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        try:
            rows = self._quote_rows([symbol.upper()])
            if not rows:
                return None
            raw = rows[0]
            bid = float(raw.get("bid") or 0)
            ask = float(raw.get("ask") or 0)
            last = float(raw.get("last") or 0)
            return {
                "symbol": str(raw.get("symbol") or symbol).upper(),
                "bp": bid, "ap": ask, "p": last,
                "bid": bid, "ask": ask, "last": last,
                "quote_age_seconds": _quote_age_seconds(raw),
                "quote_source": "tradier",
                "data_feed": (FEED_POLICY if self.base == "https://api.tradier.com/v1"
                              else "tradier_delayed_or_unknown"),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "bid_time_ms": raw.get("bid_date"),
                "ask_time_ms": raw.get("ask_date"),
                "t": _quote_timestamp(raw),
            }
        except Exception as exc:
            logger.error("get_latest_quote(%s) failed: %s", symbol, exc)
            return None

    def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        try:
            result: dict[str, dict] = {}
            for raw in self._quote_rows([str(symbol).upper() for symbol in symbols]):
                symbol = str(raw.get("symbol") or "").upper()
                if not symbol:
                    continue
                price = float(raw.get("last") or raw.get("ask") or raw.get("bid") or 0)
                previous = float(raw.get("prevclose") or 0)
                opening = float(raw.get("open") or price or 0)
                change = (price - previous) / previous * 100 if previous else 0.0
                result[symbol] = {
                    "data_feed": FEED_POLICY,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "price": price, "prev_close": previous,
                    "change_pct": change, "open_price": opening,
                    "gap_pct": ((opening - previous) / previous * 100 if previous else change),
                    "daily_vol": int(float(raw.get("volume") or 0)),
                    "quote_age_seconds": _quote_age_seconds(raw),
                }
            return result
        except Exception as exc:
            logger.error("get_snapshots failed: %s", exc)
            return {}

    def _timesales(
        self, symbol: str, interval: str, start: datetime, end: datetime,
    ) -> list[dict]:
        payload = self._get("/markets/timesales", {
            "symbol": symbol.upper(), "interval": interval,
            "start": start.astimezone(ET).strftime("%Y-%m-%d %H:%M"),
            "end": end.astimezone(ET).strftime("%Y-%m-%d %H:%M"),
            "session_filter": "open",
        })
        rows = _objects((payload.get("series") or {}).get("data"))
        return [normalized for normalized in (_bar(row) for row in rows) if normalized]

    def get_option_bars(
        self, option_symbol: str, start: datetime, end: datetime,
        *, interval: str = "1min", limit: int = 5000,
    ) -> list[dict]:
        """Return exchange-reported OHLCV bars for one exact OCC contract.

        Tradier's production Time & Sales endpoint accepts OCC option symbols.
        Keeping this separate from sampled quote observations prevents a bid or
        midpoint sample from being presented as a market candle.
        """
        if not getattr(self, "api_key", "") or not option_symbol:
            return []
        if interval not in {"1min", "5min", "15min"}:
            raise ValueError("unsupported option bar interval")
        try:
            rows = self._timesales(option_symbol, interval, start, end)
            return rows[-max(1, min(int(limit), 5000)):]
        except Exception as exc:
            logger.warning("get_option_bars(%s) failed: %s", option_symbol, exc)
            return []

    def get_bars(self, symbol: str, timeframe: str, limit: int = 100) -> tuple[list[dict], bool]:
        try:
            if not getattr(self, "api_key", "") or getattr(self, "base", "") != "https://api.tradier.com/v1":
                logger.warning("market_data_unavailable: production Tradier credentials required")
                return [], True
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                return [], True
            normalized = {"1Min": "1min", "5Min": "5min", "15Min": "15min"}
            if timeframe in {"1Day", "Day", "1D"}:
                end = datetime.now(ET).date()
                start = end - timedelta(days=max(30, min(3650, int(limit * 1.7) + 10)))
                payload = self._get("/markets/history", {
                    "symbol": symbol.upper(), "interval": "daily",
                    "start": start.isoformat(), "end": end.isoformat(),
                })
                rows = _objects((payload.get("history") or {}).get("day"))
                bars = [value for value in (_bar(row) for row in rows) if value]
                return stamp_bars(bars[-limit:], self.base), False

            hourly = timeframe in {"1Hour", "60Min"}
            interval = "15min" if hourly else normalized.get(timeframe, str(timeframe).lower())
            bars_per_day = {"1min": 390, "5min": 78, "15min": 26}.get(interval, 26)
            requested = limit * (4 if hourly else 1)
            calendar_days = max(3, min(45, int(requested / bars_per_day * 1.8) + 4))
            end = datetime.now(ET)
            start = datetime.combine(end.date() - timedelta(days=calendar_days), wall_time(9, 30), tzinfo=ET)
            bars = self._timesales(symbol, interval, start, end)
            if hourly:
                bars = _hourly(bars)
            return stamp_bars(bars[-limit:], self.base), False
        except Exception as exc:
            logger.error("get_bars(%s, %s) failed: %s", symbol, timeframe, exc)
            return [], True

    def get_session_bars(
        self, symbol: str, timeframe: str = "5Min",
    ) -> tuple[list[dict], bool, bool]:
        try:
            if not getattr(self, "api_key", "") or getattr(self, "base", "") != "https://api.tradier.com/v1":
                logger.warning("market_data_unavailable: production Tradier credentials required")
                return [], True, False
            now = datetime.now(ET)
            interval_map = {"1Min": "1min", "5Min": "5min", "15Min": "15min"}
            hourly = timeframe in {"1Hour", "60Min"}
            interval = "15min" if hourly else interval_map.get(timeframe, "1min")
            market_open = self.is_market_open()
            # During today's session an empty response is a gap, not permission
            # to substitute yesterday's candles. This also covers clock outages.
            require_today = now.weekday() < 5 and now.time() >= wall_time(9, 30)
            for days_back in range(0, 8):
                if require_today and days_back > 0:
                    logger.warning("market_data_unavailable: %s %s current session missing; no prior-day fallback", symbol, timeframe)
                    return [], True, market_open
                session_date = now.date() - timedelta(days=days_back)
                if session_date.weekday() >= 5:
                    continue
                start = datetime.combine(session_date, wall_time(9, 30), tzinfo=ET)
                end = datetime.combine(session_date, wall_time(16, 0), tzinfo=ET)
                if days_back == 0:
                    end = min(end, now)
                if end <= start:
                    continue
                bars = self._timesales(symbol, interval, start, end)
                if bars:
                    if hourly:
                        bars = _hourly(bars)
                    # Defend against a provider returning an earlier session.
                    bars = [row for row in bars if datetime.fromisoformat(
                        row['t'].replace('Z', '+00:00')).astimezone(ET).date() == session_date]
                    if not bars:
                        continue
                    return stamp_bars(bars, self.base), False, market_open and days_back == 0
            return [], False, False
        except Exception as exc:
            logger.error("get_session_bars(%s, %s) failed: %s", symbol, timeframe, exc)
            return [], True, False
