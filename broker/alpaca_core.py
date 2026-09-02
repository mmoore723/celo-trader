"""
broker/alpaca_core.py — AlpacaCoreMixin: HTTP plumbing (auth headers, GET/
POST/PATCH/DELETE with retry + circuit breaker) and the two simplest account-
level calls (get_account, is_market_open).

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Alpaca*Mixin classes
into AlpacaClient in broker/alpaca_client.py.
"""

import logging
from typing import Optional

import requests

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, STARTING_CAPITAL
from database import log_event
from logger_config import _LatencyTimer
from broker.common import (
    _retry, _debounced_log, _local_market_is_open,
    _AlpacaCircuitOpenError, _cb_is_open, _cb_record_success, _cb_record_failure,
)

logger = logging.getLogger("celo_trader.broker")


class AlpacaCoreMixin:

    def __init__(self, *, paper: bool | None = None):
        # Read live/paper mode + API keys from user-scoped settings so switching
        # the UI toggle or saving new credentials takes effect on the next bot
        from config import get_settings as _gs, ALPACA_PAPER as _env_paper, get_api_keys as _gak
        _s     = _gs()
        _keys  = _gak()   # decrypts user-specific credentials, falls back to .env
        _paper = _s.get("paper_trading", _env_paper) if paper is None else bool(paper)
        self.base = (
            "https://paper-api.alpaca.markets"
            if _paper else
            "https://api.alpaca.markets"
        )
        self.data    = "https://data.alpaca.markets"
        _api_key    = _keys.get("alpaca_api_key",    ALPACA_API_KEY)
        _secret_key = _keys.get("alpaca_secret_key", ALPACA_SECRET_KEY)
        self.api_key = _api_key
        self.secret_key = _secret_key
        self.headers = {
            "APCA-API-KEY-ID":     _api_key,
            "APCA-API-SECRET-KEY": _secret_key,
            "Content-Type":        "application/json",
        }
        if not _api_key:
            logger.warning("Alpaca keys not set — running in demo mode")
        logger.info(
            "AlpacaClient: routing to %s (paper_trading=%s)",
            self.base, _paper,
        )
        # FIX 2026-07-17: set by place_option_order() whenever an order is
        # rejected, so callers can tell WHY a fill didn't happen (e.g. Alpaca
        # genuinely has no matching position to close vs. a transient/retry-
        # worthy failure) without changing place_option_order's None-on-no-fill
        # return contract. See is_phantom_position_rejection() below.
        self.last_rejection_reason: Optional[str] = None

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _get(self, url: str, params: dict = None) -> dict:
        # Circuit open — skip the network call entirely.
        # Raise _AlpacaCircuitOpenError (not ConnectionError) so callers can
        if _cb_is_open():
            logger.debug("alpaca_cb_skip url=%s reset_at=%.0f", url, _cb_open_until)
            raise _AlpacaCircuitOpenError(
                f"circuit open until {_cb_open_until:.0f} — skipping {url}"
            )
        def call():
            with _LatencyTimer(logger, "alpaca_http_get", url=url):
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                r.raise_for_status()
                data = r.json()
                if data is None:
                    raise ValueError(f"Empty JSON response from {url}")
                return data
        try:
            result = _retry(call)
            _cb_record_success()   # successful call resets the failure counter
            return result
        except requests.exceptions.ConnectionError as e:
            _cb_record_failure()
            # Connection errors (DNS / timeout) are network-layer noise — log to file
            # only, not to the audit DB.  The circuit breaker already prevents spam.
            logger.error(
                "alpaca_get_failed",
                extra={"event": "alpaca_get_failed", "url": url, "error": str(e)},
            )
            raise
        except Exception as e:
            _e_str = str(e)
            # 403 Forbidden = free-tier SIP feed blocked — handled silently by callers.
            # 429 Too Many Requests = rate-limit hit — transient, not actionable by user.
            if "403" not in _e_str and "Forbidden" not in _e_str \
                    and "429" not in _e_str and "Too Many Requests" not in _e_str:
                _debounced_log("ERROR", "broker.alpaca", f"GET {url} failed: {e}")
            # Capture Alpaca's actual response body on HTTP errors (e.g. 401) so
            # bot.log shows *why* the request was rejected — "Unauthorized" alone
            _resp_body = None
            _resp = getattr(e, "response", None)
            if _resp is not None:
                try:
                    _resp_body = _resp.text[:300]
                except Exception:
                    pass
            logger.error(
                "alpaca_get_failed",
                extra={"event": "alpaca_get_failed", "url": url, "error": str(e), "response_body": _resp_body},
            )
            raise

    def _post(self, url: str, payload: dict) -> dict:
        def call():
            with _LatencyTimer(logger, "alpaca_http_post", url=url):
                r = requests.post(url, headers=self.headers, json=payload, timeout=10)
                r.raise_for_status()
                return r.json()
        try:
            return _retry(call)
        except Exception as e:
            log_event("ERROR", "broker.alpaca",
                      f"🔴 [Alpaca] Connection failed — could not reach the broker. "
                      f"Check your internet or API key. ({type(e).__name__})")
            # FIX: capture Alpaca's actual response body on HTTP errors, mirroring
            # _get() above. A bare "403 Client Error: Forbidden for url: .../orders"
            _resp_body = None
            _resp = getattr(e, "response", None)
            if _resp is not None:
                try:
                    _resp_body = _resp.text[:300]
                except Exception:
                    pass
            logger.error(
                "alpaca_post_failed",
                extra={"event": "alpaca_post_failed", "url": url, "error": str(e), "response_body": _resp_body},
            )
            raise

    def _patch(self, url: str, payload: dict) -> dict:
        """PATCH with single attempt — used for in-flight order modification (price step-up)."""
        r = requests.patch(url, headers=self.headers, json=payload, timeout=10)
        r.raise_for_status()
        return r.json()

    def _delete(self, url: str) -> None:
        """DELETE with retry — used for panic close."""
        def call():
            r = requests.delete(url, headers=self.headers, timeout=10)
            r.raise_for_status()
        _retry(call, retries=5, delay=1.0)   # more attempts for panic button

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        if not self.api_key:
            return {"equity": STARTING_CAPITAL, "buying_power": STARTING_CAPITAL,
                    "cash": STARTING_CAPITAL, "options_buying_power": STARTING_CAPITAL}
        data = self._get(f"{self.base}/v2/account")
        return {
            "equity":       float(data.get("equity", 0)),
            # Alpaca's prior-session closing equity is the authoritative day
            # open. Keep it so intraday restarts cannot redefine the start of
            # the trading day after gains or losses have already occurred.
            "last_equity":  float(data.get("last_equity") or 0),
            "buying_power": float(data.get("buying_power", 0)),
            "cash":         float(data.get("cash", 0)),
            # FIX 2026-06-15: this key was missing entirely, so every caller's
            # `acct.get("options_buying_power", 0)` silently fell back to its
            "options_buying_power": float(data.get("options_buying_power", 0)),
        }

    def is_market_open(self) -> bool:
        """
        Ask Alpaca whether the market is currently open.
        Returns False when the authenticated broker cannot confirm that the
        market is open. A local clock cannot detect exchange holidays or an
        emergency closure and therefore must never override broker truth.
        """
        if not self.api_key:
            return _local_market_is_open()
        try:
            data = self._get(f"{self.base}/v2/clock")
            return bool(data.get("is_open", False))
        except _AlpacaCircuitOpenError:
            return False
        except Exception as e:
            logger.warning("is_market_open check failed: %s — failing closed", e)
            return False
