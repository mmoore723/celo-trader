"""
broker/tradier_chain.py — TradierChainMixin: option chain fetch (contract
selection) and single-contract quote (position pricing) and expirations.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Tradier*Mixin classes
into TradierClient in broker/tradier_client.py.
"""

import logging
import math
from typing import Optional
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from config import MIN_OPEN_INTEREST, MAX_BID_ASK_SPREAD
from broker.tradier_market import _quote_age_seconds

logger = logging.getLogger("celo_trader.broker")


def _market_date() -> date:
    """Use the market's date, which can differ from the EC2 UTC date."""
    return datetime.now(ZoneInfo("America/New_York")).date()


class TradierChainMixin:

    def get_option_chain(
        self,
        symbol: str,
        expiration: str,
        option_type: str = "call",
        *, research_only: bool = False,
    ) -> list[dict]:
        """
        Full chain fetch — used for contract selection at trade entry only.

        FIX 2026-07-31: real incident — COIN got a valid Contract selected on
        one candle, then "no data returned" on the very next, same ticker,
        same expiration. That's not an HTTP failure (self._get()'s _retry
        already covers those) — it's Tradier's sandbox returning HTTP 200
        with an empty options list, a known intermittent quirk. That case
        skipped straight to "no_chain_data" with zero retry. One retry after
        a short delay before giving up.
        """
        if not getattr(self, "api_key", ""):
            return []
        try:
            resp = self._get("/markets/options/chains", {
                "symbol": symbol, "expiration": expiration, "greeks": "true",
            })
            options = resp.get("options", {}).get("option", [])
            if isinstance(options, dict):
                options = [options]

            if not options:
                import time as _time
                _time.sleep(0.75)
                resp = self._get("/markets/options/chains", {
                    "symbol": symbol, "expiration": expiration, "greeks": "true",
                })
                options = resp.get("options", {}).get("option", [])
                if isinstance(options, dict):
                    options = [options]

            filtered = []
            for opt in options:
                if opt.get("option_type", "").lower() != option_type.lower():
                    continue
                bid = opt.get("bid", 0) or 0
                ask = opt.get("ask", 0) or 0
                oi  = opt.get("open_interest", 0) or 0
                if research_only:
                    # Research applies its declared percentage spread/premium
                    # policy downstream, not the account's execution filters.
                    try:
                        bid, ask, oi = float(bid), float(ask), float(oi)
                        strike = float(opt.get("strike") or 0)
                    except (TypeError, ValueError):
                        continue
                    if (not all(math.isfinite(v) for v in (bid, ask, oi, strike))
                            or bid <= 0 or ask < bid or strike <= 0
                            or not opt.get("symbol")):
                        continue
                if ask == 0:
                    continue
                if not research_only and (ask - bid) > MAX_BID_ASK_SPREAD:
                    continue
                if not research_only and oi < MIN_OPEN_INTEREST:
                    continue
                filtered.append({
                    # Evidence-only fields. Existing execution values and filters
                    # below are intentionally unchanged, including legacy delta.
                    "evidence": {key: opt.get(key) for key in (
                        "bid_date", "ask_date", "bidsize", "asksize", "volume",
                        "open_interest", "contract_size", "greeks",
                    )},
                    "symbol":        opt.get("symbol"),
                    "strike":        opt.get("strike"),
                    "bid":           bid,
                    "ask":           ask,
                    "mid":           round((bid + ask) / 2, 2),
                    "spread":        round(ask - bid, 2),
                    "open_interest": oi,
                    "volume":        opt.get("volume", 0),
                    "delta":         (opt.get("greeks") or {}).get("delta", 0),
                    "iv":            (opt.get("greeks") or {}).get("mid_iv", 0),
                })
            return filtered
        except Exception as e:
            logger.error("get_option_chain(%s) failed: %s", symbol, e)
            return []

    def get_research_option_chain(self, symbol: str, expiration: str,
                                  option_type: str = "call") -> list[dict]:
        """Read valid quotes for order-free research's own contract screen.

        No execution caller uses this path. Low open interest is retained as
        evidence, not a claim of fillability; crossed/empty quotes are excluded.
        """
        return self.get_option_chain(symbol, expiration, option_type, research_only=True)

    def get_research_option_quotes(self, symbols: list[str]) -> dict:
        """Bounded read-only batch, preserving raw timestamps, sizes and Greeks.

        Missing symbols stay missing. Do not manufacture zeros or scale sizes
        into hypothetical fills. This method is exposed only to research.
        """
        symbols = sorted(set(symbols))
        if not symbols or len(symbols) > 100:
            raise ValueError("research_quote_batch_budget")
        if not getattr(self, "api_key", ""):
            return {}
        response = self._get("/markets/quotes", {
            "symbols": ",".join(symbols), "greeks": "true", "includeLotSize": "true",
        })
        received = datetime.now(timezone.utc).isoformat()
        rows = (response.get("quotes") or {}).get("quote") or []
        if isinstance(rows, dict):
            rows = [rows]
        result = {}
        for row in rows:
            if row.get("symbol") not in symbols:
                continue
            result[row["symbol"]] = {
                **{key: row.get(key) for key in (
                    "symbol", "bid", "ask", "bid_date", "ask_date", "bidsize",
                    "asksize", "volume", "open_interest", "greeks", "contract_size",
                )}, "quote_received_at": received,
            }
        return result

    # ── FIX M7: Single-contract quote (for position pricing) ─────────────────

    def get_option_quote(self, option_symbol: str) -> Optional[dict]:
        """
        Fetch bid/ask/mid for a single option contract symbol.
        Uses /markets/quotes — much cheaper than full chain fetch.
        Called every 60s while a position is open instead of the full chain.
        """
        if not getattr(self, "api_key", ""):
            return None
        try:
            resp = self._get("/markets/quotes", {
                "symbols": option_symbol,
                "greeks":  "false",
            })
            received_at = datetime.now(timezone.utc).isoformat()
            quotes = resp.get("quotes", {}).get("quote", {})
            if isinstance(quotes, list):
                quotes = quotes[0] if quotes else {}
            if not quotes:
                return None
            bid = float(quotes.get("bid", 0) or 0)
            ask = float(quotes.get("ask", 0) or 0)
            return {
                "symbol": option_symbol,
                "source_symbol": quotes.get("symbol"),
                "bid":    bid,
                "ask":    ask,
                "mid":    round((bid + ask) / 2, 4),
                "spread": round(ask - bid, 4),
                "last":   float(quotes.get("last", 0) or 0),
                "quote_age_seconds": _quote_age_seconds(quotes),
                "bid_date": quotes.get("bid_date"),
                "ask_date": quotes.get("ask_date"),
                "trade_date": quotes.get("trade_date"),
                "quote_source": "tradier",
                "quote_received_at": received_at,
            }
        except Exception as e:
            logger.error("get_option_quote(%s) failed: %s", option_symbol, e)
            return None

    # ── Expirations ───────────────────────────────────────────────────────────

    def get_research_expiration_details(
        self, symbol: str, *, minimum_dte: int = 0,
        maximum_dte: int = 7, limit: int = 8,
    ) -> dict:
        """One research-only listing read with an explicit rejection reason.

        Native get_expirations and its contract window are unchanged. Never
        infer that no options exist from a failed request or malformed body.
        """
        minimum_dte = max(0, int(minimum_dte))
        maximum_dte = max(minimum_dte, int(maximum_dte))
        limit = max(1, int(limit))
        today = _market_date()
        info = dict(reason='expiration_data_unavailable', expirations=[],
                    as_of_date=today.isoformat(), minimum_dte=minimum_dte,
                    maximum_dte=maximum_dte, listed_count=None,
                    available_dates=[], nearest_expiration=None)
        if not getattr(self, 'api_key', ''):
            info['lookup_status'] = 'missing_credentials'
            return info
        try:
            response = self._get('/markets/options/expirations', {
                'symbol': symbol, 'includeAllRoots': 'true', 'strikes': 'false',
            })
        except Exception as exc:
            # No error text, tokens, URLs, or headers enter candidate metadata.
            info['lookup_status'] = 'request_failed'
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if isinstance(status, int):
                info['http_status'] = status
            return info
        listing = response.get('expirations') if isinstance(response, dict) else None
        if not isinstance(listing, dict) or 'date' not in listing:
            info['lookup_status'] = 'unusable_response'
            return info
        raw = listing['date']
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            info['lookup_status'] = 'unusable_response'
            return info
        dates = []
        try:
            for value in raw:
                parsed = date.fromisoformat(value)
                if parsed not in dates:
                    dates.append(parsed)
        except (TypeError, ValueError):
            info['lookup_status'] = 'invalid_date'
            return info
        future = sorted(d for d in dates if d >= today)
        eligible = [d.isoformat() for d in dates
                    if minimum_dte <= (d - today).days <= maximum_dte]
        info.update(lookup_status='ok', listed_count=len(future),
                    available_dates=[d.isoformat() for d in future[:32]],
                    nearest_expiration=future[0].isoformat() if future else None,
                    expirations=eligible[:limit])
        info['reason'] = ('selected' if eligible else 'no_expirations_in_window'
                          if future else 'no_listed_expirations')
        return info

    def get_expirations(
        self, symbol: str, *, minimum_dte: int = 7,
        maximum_dte: int = 21, limit: int = 3,
    ) -> list[str]:
        """Return expirations inside an explicit market-date DTE window.

        The defaults preserve the reviewed order path. Research supplies its
        own declared window, including 0–7 DTE and 3–5 DTE studies.
        """
        if not getattr(self, "api_key", ""):
            return []
        minimum_dte = max(0, int(minimum_dte))
        maximum_dte = max(minimum_dte, int(maximum_dte))
        limit = max(1, int(limit))
        try:
            resp = self._get("/markets/options/expirations", {
                "symbol": symbol, "includeAllRoots": "true", "strikes": "false",
            })
            dates = resp.get("expirations", {}).get("date", [])
            if isinstance(dates, str):
                dates = [dates]
            today = _market_date()
            result = []
            for d in dates:
                dt = date.fromisoformat(d)
                days_out = (dt - today).days
                if minimum_dte <= days_out <= maximum_dte:
                    result.append(d)
            return result[:limit]
        except Exception as e:
            logger.error("get_expirations(%s) failed: %s", symbol, e)
            return []
