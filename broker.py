"""
broker.py — Unified broker interface for Alpaca (equity) and Tradier (options).

Fixes applied (audit round 1):
  C1  - Alpaca option order payload now uses correct v2 options format with legs[]
  S1  - Fill confirmation: poll order status until filled/rejected before returning
  M2  - close_all_positions now wrapped with _retry (3 attempts)
  M2b - Tradier place_option_order also wrapped with retry
  M7  - get_option_quote() added — single-contract price fetch via /markets/quotes
        Used by trading_logic instead of full chain fetch for position pricing
"""

import time
import logging
from datetime import datetime, date
from typing import Optional

import requests

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL,
    TRADIER_API_KEY, TRADIER_BASE_URL, TRADIER_ACCOUNT_ID,
    STARTING_CAPITAL, MIN_OPEN_INTEREST, MAX_BID_ASK_SPREAD,
)
from database import log_event
from logger_config import _LatencyTimer

logger = logging.getLogger("celo_trader.broker")

# ── Local market-hours fallback ──────────────────────────────────────────────
def _local_market_is_open() -> bool:
    """
    Pure local-time check — no network call.
    Used as a fallback when the Alpaca circuit breaker is active so
    is_market_open() doesn't incorrectly return False during regular hours.
    Returns True Monday–Friday 9:30–16:00 ET.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        if now.weekday() >= 5:
            return False
        hm = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= hm < 16 * 60
    except Exception:
        return False


# ── Audit-log debounce ────────────────────────────────────────────────────────
# Prevents the same API error flooding the system_events table on every
# auto-refresh cycle.  Key = (event_type, module, url_base); value = epoch when
# it was last written to the DB.  Errors are only re-logged after DEBOUNCE_S.
_audit_debounce: dict = {}
_AUDIT_DEBOUNCE_S = 300   # 5 minutes between identical DB error entries

def _debounced_log(level: str, module: str, message: str) -> None:
    """Write to system_events only if the same message wasn't written recently."""
    key = (level, module, message[:80])   # truncate key for dict efficiency
    now = time.time()
    if now - _audit_debounce.get(key, 0) >= _AUDIT_DEBOUNCE_S:
        _audit_debounce[key] = now
        log_event(level, module, message)

# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, retries: int = 3, delay: float = 0.5):
    """
    Linear back-off retry: 1.5s, 3s, 4.5s.

    Errors that should NOT be retried (raise immediately on attempt 1):
      • HTTP 4xx  — client/permission errors; won't change with retries
      • ConnectionError / NameResolutionError — DNS is down; 1.5s won't fix it.
        The circuit breaker in AlpacaClient handles the longer back-off.

    Errors that ARE retried (5xx, timeout, etc.):
      • HTTP 5xx  — server-side transient errors
      • Timeout   — may clear on next attempt
      • Any other unexpected exception
    """
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except requests.exceptions.HTTPError as exc:
            # 4xx = permanent client error — don't retry
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                logger.warning(
                    "HTTP %d — not retrying (client error): %s",
                    exc.response.status_code, exc,
                )
                raise
            logger.warning("Attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay * attempt)
        except requests.exceptions.ConnectionError as exc:
            # DNS / network-down errors — fail fast; circuit breaker handles back-off
            logger.warning("ConnectionError — not retrying (network issue): %s", exc)
            raise
        except Exception as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay * attempt)


# ── Alpaca circuit breaker ────────────────────────────────────────────────────
# After _CB_THRESHOLD consecutive connection failures, all Alpaca calls return
# immediately (no network attempt) until _CB_COOLDOWN seconds have elapsed.
# This prevents the tick loop from generating log spam and burning CPU during
# outages.  State is module-level so it persists across AlpacaClient instances.

_CB_THRESHOLD   = 3      # consecutive failures before opening the circuit
_CB_COOLDOWN    = 300    # seconds to wait before probing again (5 min — was 60s,
                         # which caused a "try → fail → log ERROR → wait 60s" loop
                         # every minute, flooding the Network tab all day)
_cb_fail_count  = 0      # consecutive connection failure count
_cb_open_until  = 0.0    # epoch time when circuit may close


class _AlpacaCircuitOpenError(Exception):
    """
    Raised by _get() when the circuit breaker is active.
    Callers catch this specifically so they can skip silently (the CB is
    already doing its job — no need to log it as an error every 5 minutes).
    """

def _cb_record_success():
    global _cb_fail_count, _cb_open_until
    _cb_fail_count = 0
    _cb_open_until = 0.0

def _cb_record_failure():
    global _cb_fail_count, _cb_open_until
    _cb_fail_count += 1
    if _cb_fail_count >= _CB_THRESHOLD:
        _cb_open_until = time.time() + _CB_COOLDOWN
        logger.warning(
            "alpaca_circuit_open: %d consecutive connection failures — "
            "pausing Alpaca calls for %ds",
            _cb_fail_count, _CB_COOLDOWN,
        )

def _cb_is_open() -> bool:
    """Return True if the circuit is open (calls should be skipped)."""
    if _cb_open_until and time.time() < _cb_open_until:
        return True
    return False


# ── Alpaca client ─────────────────────────────────────────────────────────────

class AlpacaClient:
    """Alpaca REST API v2 — equity bars, account data, paper/live options orders."""

    def __init__(self):
        self.base    = ALPACA_BASE_URL
        self.data    = "https://data.alpaca.markets"
        self.headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            "Content-Type":        "application/json",
        }
        if not ALPACA_API_KEY:
            logger.warning("Alpaca keys not set — running in demo mode")

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _get(self, url: str, params: dict = None) -> dict:
        # Circuit open — skip the network call entirely.
        # Raise _AlpacaCircuitOpenError (not ConnectionError) so callers can
        # distinguish "CB protecting us" from a real network failure and skip
        # silently instead of logging an ERROR every 5 minutes.
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
            # Neither should flood the audit log.
            if "403" not in _e_str and "Forbidden" not in _e_str \
                    and "429" not in _e_str and "Too Many Requests" not in _e_str:
                _debounced_log("ERROR", "broker.alpaca", f"GET {url} failed: {e}")
            # Capture Alpaca's actual response body on HTTP errors (e.g. 401) so
            # bot.log shows *why* the request was rejected — "Unauthorized" alone
            # doesn't distinguish a bad key, an unconfirmed account, or a network
            # intermediary (proxy/VPN) intercepting the request. Truncated to
            # avoid log bloat; the JSON formatter's secret-redaction still
            # applies to this field.
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
            # gives no actionable information — Alpaca's JSON body usually says
            # *why* the order was rejected (e.g. account restricted from trading,
            # options trading not approved at this level, insufficient buying
            # power). Without this, 403s on every order placement are
            # indistinguishable from a bad API key. Truncated to avoid log bloat;
            # the JSON formatter's secret-redaction still applies to this field.
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

    def _delete(self, url: str) -> None:
        """DELETE with retry — used for panic close."""
        def call():
            r = requests.delete(url, headers=self.headers, timeout=10)
            r.raise_for_status()
        _retry(call, retries=5, delay=1.0)   # more attempts for panic button

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        if not ALPACA_API_KEY:
            return {"equity": STARTING_CAPITAL, "buying_power": STARTING_CAPITAL,
                    "cash": STARTING_CAPITAL, "options_buying_power": STARTING_CAPITAL}
        data = self._get(f"{self.base}/v2/account")
        return {
            "equity":       float(data.get("equity", 0)),
            "buying_power": float(data.get("buying_power", 0)),
            "cash":         float(data.get("cash", 0)),
            # FIX 2026-06-15: this key was missing entirely, so every caller's
            # `acct.get("options_buying_power", 0)` silently fell back to its
            # default of 0 — the dashboard's "Options Buying Power" card and
            # the entry-sizing logic in trading_logic.py have been showing/
            # using a hardcoded 0.0 regardless of the REAL value Alpaca
            # returns in this field. Now actually read it from Alpaca.
            "options_buying_power": float(data.get("options_buying_power", 0)),
        }

    def is_market_open(self) -> bool:
        """
        Ask Alpaca whether the market is currently open.
        Falls back to local ET time check when the circuit breaker is active
        (avoids showing MARKET CLOSED all day just because Alpaca is unreachable).
        Returns False on unknown API error (safe default — don't trade if unsure).
        """
        if not ALPACA_API_KEY:
            return _local_market_is_open()
        try:
            data = self._get(f"{self.base}/v2/clock")
            return bool(data.get("is_open", False))
        except _AlpacaCircuitOpenError:
            # CB is protecting us — use local time as fallback so the UI
            # doesn't incorrectly show MARKET CLOSED during trading hours.
            return _local_market_is_open()
        except Exception as e:
            logger.warning("is_market_open check failed: %s — assuming closed", e)
            return False

    # ── Market data ───────────────────────────────────────────────────────────

    def get_bars(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> tuple[list[dict], bool]:
        """
        Fetch OHLCV bars.
        Returns (bars, is_error) — caller can distinguish empty-market from API failure.
        is_error=True means the API call failed; is_error=False means success (may be empty).
        """
        import datetime as _dt
        tf_map = {"5Min": "5Min", "15Min": "15Min", "60Min": "1Hour", "1Hour": "1Hour",
                  "1Day": "1Day", "Day": "1Day", "1D": "1Day"}
        tf  = tf_map.get(timeframe, timeframe)
        url = f"{self.data}/v2/stocks/{symbol}/bars"

        # For daily bars Alpaca only returns the current partial bar without a start date
        # Explicitly request 6 months back to get full historical daily data
        # Always request IEX feed — free-tier Alpaca keys 403 on SIP.
        # NOTE: IEX feed does NOT support session=extended — that param causes 400.
        # Extended hours bars come from yfinance in the chart API endpoint.
        params = {"timeframe": tf, "limit": limit, "adjustment": "split", "feed": "iex"}
        if tf == "1Day":
            start = (_dt.datetime.utcnow() - _dt.timedelta(days=180)).strftime("%Y-%m-%d")
            params["start"] = start
        else:
            # FIX 2026-06-20: intraday timeframes (5Min/15Min/1Hour) had NO start
            # date at all — Alpaca's implicit default window without one is too
            # narrow, and on a day with no trading yet/at all (e.g. a weekend, or
            # before the first bar of a session prints) it has nothing to return
            # and responds with "bars": null (not []) for a successful 200. That
            # null then crashed the len() call below instead of being treated as
            # a normal empty result. Surfaced by playbook_examples.py failing on
            # all 5 tickers when run on a Saturday. Giving every intraday request
            # an explicit lookback (sized to comfortably cover `limit` bars across
            # weekends/holidays) makes the response deterministic regardless of
            # what day this is called on.
            _bars_per_day = {"5Min": 78, "15Min": 26, "1Hour": 7}.get(tf, 78)
            _trading_days_needed = max(1, -(-limit // _bars_per_day))  # ceil division
            # Pad 1.6x for weekends/holidays, plus a flat 5-day floor so small
            # `limit` requests still get a sane minimum lookback window.
            _calendar_days_back = max(5, int(_trading_days_needed * 1.6) + 3)
            start = (_dt.datetime.utcnow() - _dt.timedelta(days=_calendar_days_back)).strftime("%Y-%m-%d")
            params["start"] = start

        try:
            resp = self._get(url, params)
            # FIX 2026-06-20: resp.get("bars", []) only applies the [] default when
            # the "bars" KEY IS MISSING. Alpaca can return the key present with a
            # literal null value ({"bars": null, ...}) for a successful empty
            # result — `.get()` then returns None, not [], and len(None) crashes.
            # `or []` catches both "key missing" and "key present but None".
            bars = resp.get("bars") or []
            logger.debug("Got %d bars for %s %s", len(bars), symbol, timeframe)
            return bars, False          # success — possibly empty list
        except _AlpacaCircuitOpenError:
            # Circuit is protecting us — silent skip, no error log
            logger.debug("get_bars(%s, %s) skipped — CB active", symbol, timeframe)
            return [], True
        except Exception as e:
            logger.error("get_bars(%s, %s) failed: %s", symbol, timeframe, e)
            return [], True             # API error — caller should skip this TF

    def get_session_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
    ) -> tuple[list[dict], bool, bool]:
        """
        Fetch the current trading session's bars (9:30 AM – 4:00 PM ET).
        If the market is closed, returns the most recent completed session.

        Returns (bars, is_error, is_live_session).
          bars            – OHLCV bar dicts from Alpaca
          is_error        – True if the API call failed
          is_live_session – True if the market is currently open
        """
        import datetime as _dt
        try:
            import pytz as _pytz
            ET     = _pytz.timezone("America/New_York")
            now_et = _dt.datetime.now(ET)
        except ImportError:
            # Fallback: approximate EDT (UTC−4)
            _tz    = _dt.timezone(_dt.timedelta(hours=-4))
            now_et = _dt.datetime.utcnow().replace(tzinfo=_tz)
            ET     = None

        tf_map = {
            "1Min": "1Min", "5Min": "5Min", "15Min": "15Min",
            "1Hour": "1Hour", "60Min": "1Hour", "1Day": "1Day",
        }
        tf       = tf_map.get(timeframe, timeframe)
        is_live  = self.is_market_open()

        # ── Resolve the extended session date ────────────────────────────────
        # Extended trading day: pre-market 04:00 → post-market 20:00 ET.
        # We only roll back to the previous day if it's before 04:00 today
        # (truly overnight — no meaningful bar data yet).
        # Between 04:00 and 09:30: show today's pre-market bars.
        # Between 09:30 and 16:00: regular session (ORB window).
        # Between 16:01 and 20:00: show today's post-market bars.
        session_date = now_et.date()
        if ET is not None:
            _pm_start_today = ET.localize(
                _dt.datetime.combine(session_date, _dt.time(4, 0))
            )
        else:
            _pm_start_today = _dt.datetime.combine(
                session_date, _dt.time(4, 0)
            ).replace(tzinfo=now_et.tzinfo)

        # Roll back only if before 04:00 — pre-market hasn't started yet
        if now_et < _pm_start_today:
            session_date -= _dt.timedelta(days=1)

        # Skip Saturday (5) and Sunday (6)
        while session_date.weekday() >= 5:
            session_date -= _dt.timedelta(days=1)

        # ── Build ISO 8601 start/end with ET offset ───────────────────────────
        # Pre-market opens at 04:00; post-market closes at 20:00.
        if ET is not None:
            session_open  = ET.localize(
                _dt.datetime.combine(session_date, _dt.time(4, 0, 0))
            )
            session_close = ET.localize(
                _dt.datetime.combine(session_date, _dt.time(20, 0, 0))
            )
        else:
            _tz2 = now_et.tzinfo
            session_open  = _dt.datetime.combine(
                session_date, _dt.time(4, 0, 0)
            ).replace(tzinfo=_tz2)
            session_close = _dt.datetime.combine(
                session_date, _dt.time(20, 0, 0)
            ).replace(tzinfo=_tz2)

        # For an active extended session fetch up to right now;
        # for a fully completed session (before today's 04:00) fetch the full day.
        _is_extended_live = (
            session_date == now_et.date() and now_et >= _pm_start_today
        )
        bar_end = min(now_et, session_close) if _is_extended_live else session_close

        url    = f"{self.data}/v2/stocks/{symbol}/bars"

        # Choose feed based on data plan.  Free plan: skip SIP entirely to avoid
        # a guaranteed 403 round-trip; use IEX (regular session only).
        # Premium plan: try SIP first (extended hours + pre-market included).
        from config import get_settings as _gs_broker
        _is_premium = _gs_broker().get("alpaca_data_plan", "free") == "premium"
        _initial_feed = "sip" if _is_premium else "iex"

        params = {
            "timeframe":  tf,
            "start":      session_open.isoformat(),
            "end":        bar_end.isoformat(),
            "limit":      1000,         # 1m extended session = ~960 bars (04:00–20:00)
            "adjustment": "split",
            "feed":       _initial_feed,
        }

        try:
            resp = self._get(url, params)
            bars = resp.get("bars", [])
            logger.info(
                "get_session_bars(%s %s): %d bars for %s (extended_live=%s)",
                symbol, timeframe, len(bars), session_date, _is_extended_live,
            )
            if bars:
                return bars, False, _is_extended_live
            logger.warning(
                "get_session_bars: no bars for %s on %s — trying 2-day window",
                symbol, session_date,
            )
        except _AlpacaCircuitOpenError:
            # Circuit breaker active — skip silently, no error log
            logger.debug("get_session_bars(%s, %s) skipped — CB active", symbol, timeframe)
            return [], True, False
        except Exception as e:
            _e_str = str(e)
            # 403 on SIP feed = free-tier key; retry immediately with IEX feed
            # before falling through to the 2-day window logic.
            if "403" in _e_str:
                logger.warning(
                    "get_session_bars(%s): SIP feed 403 (free-tier key) — retrying with IEX feed",
                    symbol,
                )
                try:
                    params_iex = {**params, "feed": "iex"}
                    resp_iex   = self._get(url, params_iex)
                    bars_iex   = resp_iex.get("bars", [])
                    if bars_iex:
                        logger.info(
                            "get_session_bars(%s): IEX fallback got %d bars", symbol, len(bars_iex)
                        )
                        return bars_iex, False, _is_extended_live
                except Exception as e_iex:
                    logger.warning("get_session_bars(%s): IEX fallback also failed: %s", symbol, e_iex)

                # ── Extended-hours not available on free tier — fall back to
                # regular session window (09:30–16:00) with IEX feed.  This
                # prevents orphaned pre-market stub bars on the chart.
                try:
                    _reg_open  = ET.localize(
                        _dt.datetime.combine(session_date, _dt.time(9, 30, 0))
                    ) if ET else _dt.datetime.combine(
                        session_date, _dt.time(9, 30, 0)
                    ).replace(tzinfo=now_et.tzinfo)
                    _reg_close = ET.localize(
                        _dt.datetime.combine(session_date, _dt.time(16, 0, 0))
                    ) if ET else _dt.datetime.combine(
                        session_date, _dt.time(16, 0, 0)
                    ).replace(tzinfo=now_et.tzinfo)
                    _reg_end   = min(now_et, _reg_close) if _is_extended_live else _reg_close

                    params_reg = {
                        "timeframe":  tf,
                        "start":      _reg_open.isoformat(),
                        "end":        _reg_end.isoformat(),
                        "limit":      500,
                        "adjustment": "split",
                        "feed":       "iex",
                    }
                    resp_reg = self._get(url, params_reg)
                    bars_reg = resp_reg.get("bars", [])
                    if bars_reg:
                        logger.info(
                            "get_session_bars(%s): regular-session IEX got %d bars "
                            "(pre-market not available on free tier)",
                            symbol, len(bars_reg),
                        )
                        # Only surface to audit feed if user is on premium plan
                        # (they expected SIP / pre-market to work).
                        # On free plan this is the normal fallback — no card needed.
                        if _is_premium:
                            log_event(
                                "INFO", "broker.alpaca",
                                f"🟡 [{symbol}] Pre-market data not available — "
                                f"using regular session (9:30–4:00 PM) data only.",
                            )
                        return bars_reg, False, False
                except Exception as e_reg:
                    logger.warning(
                        "get_session_bars(%s): regular-session fallback also failed: %s",
                        symbol, e_reg,
                    )
            else:
                logger.error(
                    "get_session_bars(%s, %s) failed: %s — trying 2-day window", symbol, timeframe, e
                )

        # ── Attempt 2: previous trading day (full extended hours) ─────────────
        # Current day has no data yet (holiday, weekend edge case, API delay).
        # Pull the previous day's full extended session (04:00–20:00) so the
        # chart always has visible candlestick data including its pre/post market.
        try:
            prev_date = session_date - _dt.timedelta(days=1)
            while prev_date.weekday() >= 5:          # skip Saturday / Sunday
                prev_date -= _dt.timedelta(days=1)

            if ET is not None:
                two_day_start = ET.localize(
                    _dt.datetime.combine(prev_date, _dt.time(4, 0, 0))
                )
                two_day_end = ET.localize(
                    _dt.datetime.combine(prev_date, _dt.time(20, 0, 0))
                )
            else:
                two_day_start = _dt.datetime.combine(
                    prev_date, _dt.time(4, 0, 0)
                ).replace(tzinfo=now_et.tzinfo)
                two_day_end = _dt.datetime.combine(
                    prev_date, _dt.time(20, 0, 0)
                ).replace(tzinfo=now_et.tzinfo)

            params_2d = {
                "timeframe":  tf,
                "start":      two_day_start.isoformat(),
                "end":        two_day_end.isoformat(),
                "limit":      1000,     # extended day ~960 1m bars; 1000 is safe ceiling
                "adjustment": "split",
                "feed":       "iex",
            }
            resp2 = self._get(url, params_2d)
            bars  = resp2.get("bars", [])
            if bars:
                logger.info(
                    "2-day extended fallback: got %d bars from %s",
                    len(bars), prev_date,
                )
                return bars, False, False   # previous day — not live
            logger.warning("2-day fallback also empty for %s — using limit fetch", symbol)
        except Exception as e2:
            logger.warning("2-day bars fetch failed for %s: %s — using limit fetch", symbol, e2)

        # ── Attempt 3: plain limit-based fetch (no date filter) ───────────────
        bars, err = self.get_bars(symbol, timeframe, limit=500)

        # ── Attempt 4: yfinance — circuit breaker open OR bars don't cover 9:30 ──
        # Alpaca IEX on the free plan sometimes returns only recent bars when the
        # bot starts mid-session, leaving the 9:30–9:40 opening-range window empty.
        # This causes "Opening range incomplete: 1/3 bars" on every tick and
        # prevents the ORB strategy (and any other OR-dependent strategy) from
        # evaluating correctly.  yfinance 1m bars always cover the full regular
        # session from open to current time — use them as a reliable supplement.
        _need_yf = err   # definitely needed if Alpaca failed entirely
        if not err and bars:
            # Check if the OR window (9:30–9:40 ET) is covered.  bars_to_df
            # converts Alpaca's UTC timestamps → ET tz-naive, so .hour/.minute work.
            try:
                from signals import bars_to_df as _b2df
                import pandas as _pd_chk
                _tmp = _b2df(bars)
                _need_yf = not any(
                    (int(r["time"].hour) == 9 and int(r["time"].minute) in {30, 35, 40})
                    for _, r in _tmp.iterrows()
                )
                if _need_yf:
                    logger.info(
                        "get_session_bars(%s): Alpaca bars don't cover 9:30 OR window "
                        "(earliest bar: %s) — supplementing with yfinance",
                        symbol,
                        _tmp["time"].iloc[0] if not _tmp.empty else "N/A",
                    )
            except Exception:
                pass  # if the check itself fails, skip yfinance

        if _need_yf:
            try:
                import yfinance as _yf_gsb
                import pandas as _pd_gsb
                import pytz as _pytz_gsb
                _ET_gsb = _pytz_gsb.timezone("America/New_York")
                _yf_interval_map = {
                    "1Min": "1m", "5Min": "5m", "15Min": "15m",
                    "1Hour": "60m", "60Min": "60m",
                }
                _yf_iv    = _yf_interval_map.get(timeframe, "1m")
                _yf_start = session_date.strftime("%Y-%m-%d")
                _yf_end   = (_dt.date.today() + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
                _yf_raw   = _yf_gsb.download(
                    symbol,
                    start=_yf_start,
                    end=_yf_end,
                    interval=_yf_iv,
                    prepost=False,          # regular session only — no pre/post noise
                    progress=False,
                    auto_adjust=True,
                )
                if not _yf_raw.empty:
                    # Flatten MultiIndex columns (yfinance ≥ 0.2)
                    if hasattr(_yf_raw.columns, "get_level_values"):
                        _yf_raw.columns = _yf_raw.columns.get_level_values(0)
                    _yf_raw = _yf_raw.rename(columns={
                        "Open": "o", "High": "h", "Low": "l",
                        "Close": "c", "Volume": "v",
                    })
                    _yf_raw.index.name = "t"
                    _yf_raw = _yf_raw.reset_index()
                    # Convert UTC-aware index → ET-offset ISO string (Alpaca bar format)
                    _yf_raw["t"] = (
                        _pd_gsb.to_datetime(_yf_raw["t"], utc=True)
                        .dt.tz_convert(_ET_gsb)
                        .dt.strftime("%Y-%m-%dT%H:%M:%S%z")
                    )
                    _yf_bars = _yf_raw[["t", "o", "h", "l", "c", "v"]].to_dict("records")
                    if _yf_bars:
                        logger.info(
                            "get_session_bars(%s, %s): yfinance fallback got %d bars "
                            "(Alpaca CB open=%s, OR-missing=%s)",
                            symbol, timeframe, len(_yf_bars), err, _need_yf and not err,
                        )
                        return _yf_bars, False, is_live
            except Exception as _e_yf:
                logger.warning(
                    "get_session_bars(%s): yfinance fallback failed: %s", symbol, _e_yf
                )

        return bars, err, is_live

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        url = f"{self.data}/v2/stocks/{symbol}/quotes/latest"
        try:
            return self._get(url).get("quote")
        except Exception as e:
            logger.error("get_latest_quote(%s) failed: %s", symbol, e)
            return None

    def get_snapshots(self, symbols: list[str]) -> dict[str, dict]:
        """
        Fetch latest price + prev-close for multiple symbols in ONE API call.

        Uses Alpaca's /v2/stocks/snapshots endpoint (free-tier supported).
        Returns a dict keyed by symbol:
          {
            "SPY": {"price": 528.41, "prev_close": 526.10, "change_pct": 0.44},
            ...
          }
        Falls back to an empty dict on any error — caller should handle gracefully.
        """
        if not symbols:
            return {}
        url = f"{self.data}/v2/stocks/snapshots"
        try:
            data = self._get(url, params={"symbols": ",".join(symbols), "feed": "iex"})
            result: dict[str, dict] = {}
            for sym, snap in (data or {}).items():
                try:
                    _latest = snap.get("latestTrade") or snap.get("latestQuote") or {}
                    _daily  = snap.get("dailyBar") or snap.get("prevDailyBar") or {}
                    _prev   = snap.get("prevDailyBar") or {}
                    _price  = float(
                        _latest.get("p")           # latestTrade price
                        or _latest.get("ap")        # latestQuote ask
                        or _daily.get("c")          # dailyBar close
                        or 0
                    )
                    _prev_close = float(_prev.get("c") or _daily.get("o") or _price or 0)
                    _chg = (_price - _prev_close) / _prev_close * 100 if _prev_close else 0.0
                    # open_price: today's open bar (available after 9:30 ET)
                    # daily_vol:  today's cumulative volume so far (for RVOL calc)
                    _open = float(_daily.get("o") or _price or 0)
                    _gap_pct = (
                        (_open - _prev_close) / _prev_close * 100
                        if _prev_close and _open else _chg
                    )
                    result[sym] = {
                        "price":      _price,
                        "prev_close": _prev_close,
                        "change_pct": _chg,
                        "open_price": _open,
                        "gap_pct":    round(_gap_pct, 4),
                        "daily_vol":  int(_daily.get("v") or 0),
                    }
                except Exception:
                    pass   # skip malformed symbol, continue
            return result
        except Exception as e:
            logger.debug("get_snapshots failed: %s", e)
            return {}

    # ── Options orders (FIX C1: correct Alpaca v2 options format) ────────────

    def place_option_order(
        self,
        symbol: str,            # OCC option symbol e.g. AMC240119C00005000
        qty: int,
        side: str,              # 'buy' or 'sell'
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Submit an options order via Alpaca v2 OPTIONS endpoint.

        FIX C2: Single-leg option orders use the SAME FLAT shape as equity
        orders — symbol/qty/side/type/time_in_force at the top level.
        The previous "order_class: simple" + "legs": [...] shape is only
        valid for order_class "mleg" (multi-leg spreads); sending it for a
        single-leg order is rejected by Alpaca with 422 Unprocessable Entity
        (this was the cause of the JPM order failure on 2026-06-11).

        Alpaca options docs (valid single-leg payload examples):
        https://docs.alpaca.markets/docs/options-orders
        """
        if not ALPACA_API_KEY:
            logger.warning("Alpaca keys missing — order not sent")
            return None

        payload: dict = {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          side,
            "time_in_force": "day",
        }

        # Options orders should always be limit to avoid bad fills
        if order_type == "limit" and limit_price:
            payload["type"]        = "limit"
            payload["limit_price"] = str(round(limit_price, 2))
        else:
            payload["type"] = "market"

        logger.info(
            "order_submitted",
            extra={
                "event": "order_submitted",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "order_type": order_type,
                "limit_price": limit_price,
            },
        )
        try:
            order = self._post(f"{self.base}/v2/orders", payload)
            order_id = order.get("id", "")
            log_event("INFO", "broker.alpaca",
                      f"🟢 [{symbol}] Order sent to Alpaca — {side.upper()} {symbol} "
                      f"(order ID: {order_id[:8]}…). Waiting for fill confirmation.")

            # FIX S1: Poll for fill confirmation — don't record trade on pending
            confirmed = self._wait_for_fill(order_id)
            if not confirmed:
                log_event("ERROR", "broker.alpaca",
                          f"🔴 [{symbol}] Order did not fill in time — no position recorded. "
                          f"Will look for the next setup.")
                logger.error(
                    "order_fill_timeout",
                    extra={
                        "event": "order_fill_timeout",
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": side,
                    },
                )
                return None
            return confirmed

        except Exception as e:
            # FIX: surface Alpaca's ACTUAL rejection reason in the human-readable
            # audit log, instead of just the Python exception type (e.g.
            # "HTTPError"). Previously a 403 "insufficient options buying power"
            # looked identical in the dashboard's audit feed to a network outage
            # or bad API key — the user had no way to know WHY orders were
            # failing without reading raw JSON logs. Alpaca's error body (now
            # captured by _post() above) usually contains a "message" field
            # plus, for buying-power rejections, "options_buying_power" and
            # "cost_basis" — pull those out for a specific, actionable message.
            _reason = type(e).__name__
            _resp = getattr(e, "response", None)
            if _resp is not None:
                try:
                    _body = _resp.json()
                    _msg  = _body.get("message", "")
                    if _msg == "insufficient options buying power":
                        _avail = float(_body.get("options_buying_power", 0))
                        _need  = float(_body.get("cost_basis", 0))
                        _reason = (
                            f"insufficient options buying power — this order "
                            f"needs ${_need:,.2f} but only ${_avail:,.2f} is "
                            f"available. Check your Alpaca paper dashboard's "
                            f"Positions tab for an open position tying up funds."
                        )
                    elif _msg:
                        _reason = _msg
                except Exception:
                    pass
            log_event("ERROR", "broker.alpaca",
                      f"🔴 [{symbol}] Order rejected — {_reason}. No position opened.")
            logger.error(
                "order_execution_failed",
                extra={
                    "event": "order_execution_failed",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(e),
                },
            )

            # FIX 2026-06-15 GHOST PREVENTION: the exception above means
            # self._post() raised BEFORE returning an order_id, so we have no
            # order_id to cancel directly. But on 2026-06-15, several orders
            # that raised a 403 here were nonetheless ACCEPTED by Alpaca as
            # resting limit orders — they later filled hours later as ghost
            # positions with no stop-loss/profit-target/time-box. Search for
            # any resting order on this symbol and cancel it so a "failed"
            # order can never silently fill unsupervised.
            try:
                _orphans = self.get_open_orders(symbol=symbol)
                for _o in _orphans:
                    _oid = _o.get("id", "")
                    if self.cancel_order(_oid):
                        log_event(
                            "WARNING", "broker.alpaca",
                            f"🟡 [{symbol}] Found and cancelled a resting order "
                            f"(ID: {_oid[:8]}…) left behind by the failed "
                            f"request above — it can no longer fill as a "
                            f"ghost position."
                        )
                        logger.warning(
                            "orphan_order_cancelled",
                            extra={"event": "orphan_order_cancelled", "symbol": symbol, "order_id": _oid},
                        )
            except Exception as _ce:
                logger.warning("orphan_order_sweep_failed: %s", _ce)

            return None

    def _wait_for_fill(self, order_id: str, max_wait: int = 300) -> Optional[dict]:
        """
        Poll order status until filled or rejected.
        Returns the order dict if filled, None if rejected/cancelled/timeout.

        FIX S1: Live orders start as 'pending_new', not 'filled'.
        Recording a trade before fill confirmation creates ghost positions.
        """
        if not order_id or order_id == "paper_simulated":
            return {"id": order_id, "status": "filled"}   # paper — trust it

        terminal_states = {"filled", "expired", "canceled", "cancelled",
                           "rejected", "stopped", "suspended", "done_for_day"}
        for _ in range(max_wait):
            try:
                order = self._get(f"{self.base}/v2/orders/{order_id}")
                status = order.get("status", "")
                logger.debug("Order %s status: %s", order_id, status)
                if status == "filled":
                    filled_price = float(order.get("filled_avg_price") or 0)
                    logger.info("Order %s filled @ $%.4f", order_id, filled_price)
                    order["confirmed_fill_price"] = filled_price
                    return order
                if status in terminal_states:
                    logger.warning("Order %s ended with status: %s", order_id, status)
                    return None
            except Exception as e:
                logger.warning("Status poll failed for %s: %s", order_id, e)
            time.sleep(1)

        logger.error("Order %s timed out waiting for fill after %ds", order_id, max_wait)
        # GHOST PREVENTION: a timed-out order is still resting in Alpaca and
        # can fill hours later as an unsupervised position with no stop-loss.
        # Cancel it immediately so it never silently fills.
        try:
            if self.cancel_order(order_id):
                log_event(
                    "WARNING", "broker.alpaca",
                    f"🟡 Timed-out order ({order_id[:8]}…) cancelled to prevent "
                    f"a ghost position — the order did not fill within {max_wait}s."
                )
                logger.warning(
                    "timed_out_order_cancelled",
                    extra={"event": "timed_out_order_cancelled", "order_id": order_id},
                )
        except Exception as _ce:
            logger.warning("Failed to cancel timed-out order %s: %s", order_id, _ce)
        return None

    # ── Panic close (FIX M2: retry wrapper) ──────────────────────────────────

    def close_all_positions(self) -> None:
        """
        Panic button — liquidates everything. Retries 5 times so one network
        hiccup doesn't leave positions open.
        """
        try:
            self._delete(f"{self.base}/v2/positions")
            log_event("WARNING", "broker.alpaca",
                      "🔴 Emergency close triggered — all positions have been liquidated.")
            logger.warning("PANIC BUTTON: all positions closed")
        except Exception as e:
            log_event("CRITICAL", "broker.alpaca",
                      f"🔴 [Alpaca] Emergency close FAILED after multiple retries — "
                      f"positions may still be open! Manual action required. ({type(e).__name__})")
            logger.critical("close_all_positions failed after retries: %s", e)

    def get_positions(self) -> list[dict]:
        try:
            result = self._get(f"{self.base}/v2/positions")
            return result if isinstance(result, list) else []
        except Exception:
            return []

    # ── Single-position close (NEW 2026-06-15 — Trade Journal close button) ──
    # close_all_positions() above liquidates EVERYTHING (panic button). This
    # method closes just ONE position by its OCC option symbol, via
    # DELETE /v2/positions/{symbol} — used by the Trade Journal's per-row
    # "Close Position" button so the user can close individual untracked/
    # ghost positions one at a time instead of an all-or-nothing panic close.
    def close_position(self, symbol: str) -> bool:
        """
        Close a single open position by its OCC option symbol.
        Returns True if the close request succeeded, False otherwise.
        """
        if not symbol:
            return False
        try:
            self._delete(f"{self.base}/v2/positions/{symbol}")
            log_event("WARNING", "broker.alpaca",
                      f"🟡 Manually closed position {symbol} from the Trade Journal.")
            logger.warning("manual_position_close: %s", symbol)
            return True
        except Exception as e:
            log_event("ERROR", "broker.alpaca",
                      f"🔴 [{symbol}] Failed to close position from Trade Journal "
                      f"after multiple retries — it may still be open. ({type(e).__name__})")
            logger.error("close_position failed for %s: %s", symbol, e)
            return False

    # ── Orphaned-order cleanup (FIX 2026-06-15 ghost positions) ───────────────
    # On 2026-06-15 a 403 response to a /v2/orders POST was treated as "order
    # never placed" (place_option_order returned None, nothing written to the
    # DB) — but Alpaca had actually ACCEPTED the order as a resting limit order,
    # which then filled hours later, unsupervised, as a "ghost" position with
    # no stop-loss/profit-target/time-box. These two methods let callers find
    # and cancel any such resting orders so they can never silently fill again.

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """
        Return all currently-open (resting) orders, optionally filtered to a
        single OCC option symbol. Returns [] on any error — callers should
        treat that as "unknown" rather than "definitely none", but an empty
        list is also the correct/expected steady-state result.
        """
        try:
            params = {"status": "open"}
            if symbol:
                params["symbols"] = symbol
            result = self._get(f"{self.base}/v2/orders", params=params)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning("get_open_orders failed: %s", e)
            return []

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a single resting order by ID. Returns True if the cancel
        request succeeded (Alpaca returns 204 No Content), False otherwise.
        """
        if not order_id:
            return False
        try:
            self._delete(f"{self.base}/v2/orders/{order_id}")
            logger.info("order_cancelled", extra={"event": "order_cancelled", "order_id": order_id})
            return True
        except Exception as e:
            logger.error(
                "order_cancel_failed",
                extra={"event": "order_cancel_failed", "order_id": order_id, "error": str(e)},
            )
            return False


# ── Tradier client ────────────────────────────────────────────────────────────

class TradierClient:
    """
    Tradier REST API — options chain data, single-contract quotes, order routing.
    """

    def __init__(self):
        self.base    = TRADIER_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {TRADIER_API_KEY}",
            "Accept":        "application/json",
        }
        if not TRADIER_API_KEY:
            logger.warning("Tradier API key not set — options data unavailable")

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base}{endpoint}"
        def call():
            with _LatencyTimer(logger, "tradier_http_get", endpoint=endpoint):
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                r.raise_for_status()
                # Tradier sandbox endpoints occasionally return an empty body
                # (e.g. /markets/fundamentals/calendars on free-tier keys).
                # Guard against JSONDecodeError so the retry loop is not triggered
                # for a quota/permissions issue that won't resolve on retry.
                if not r.text or not r.text.strip():
                    logger.warning(
                        "tradier_empty_body: %s returned empty response — skipping retries",
                        endpoint,
                    )
                    return {}   # safe empty dict; callers check .get() with defaults
                # Tradier occasionally returns an HTML error page or XML quota
                # response (especially on free-tier rate limits) that causes
                # r.json() to raise JSONDecodeError: "Expecting value: line 1 col 1".
                # Catch it, log the raw body for debugging, and return {} so the
                # caller's .get() chain returns its default instead of crashing.
                try:
                    return r.json()
                except Exception as _jde:
                    _ctype = r.headers.get("Content-Type", "")
                    _body  = r.text[:300]
                    # Detect the specific case where Tradier (or a proxy in front of
                    # it) silently redirected us to its ReadMe.io-hosted docs/marketing
                    # site instead of returning JSON from the API host. This happens
                    # with an invalid/expired token or an endpoint not entitled on the
                    # current plan — it is NOT transient, so retrying changes nothing.
                    _is_docs_redirect = (
                        "text/html" in _ctype.lower()
                        or _body.lstrip().lower().startswith(("<!doctype", "<html"))
                    )
                    logger.error(
                        "tradier_json_decode: %s status=%d url=%s redirected_to=%s "
                        "content_type=%s body=%r error=%s",
                        endpoint, r.status_code, url, r.url, _ctype, _body, _jde,
                    )
                    if _is_docs_redirect:
                        # Debounced (5 min) — this fires every poll cycle otherwise
                        # and floods the Live Trading audit log with duplicates.
                        _debounced_log(
                            "ERROR", "broker.tradier",
                            f"🔴 [Tradier] {endpoint} returned an HTML page instead of "
                            f"JSON (status {r.status_code}) — this looks like a "
                            f"redirect to Tradier's documentation/marketing site, "
                            f"usually caused by an invalid/expired TRADIER_API_KEY or "
                            f"an endpoint not enabled for this account. Retrying will "
                            f"NOT fix this — verify your Tradier sandbox API key and "
                            f"TRADIER_BASE_URL in .env."
                        )
                    else:
                        _debounced_log(
                            "ERROR", "broker.tradier",
                            f"🔴 [Tradier] Received an unreadable response (not JSON) — "
                            f"status {r.status_code}. This often means a rate-limit or "
                            f"server issue."
                        )
                    return {}
        try:
            return _retry(call)
        except Exception as e:
            log_event("ERROR", "broker.tradier",
                      f"🔴 [Tradier] Connection failed — could not reach the API. "
                      f"Check your internet or API key. ({type(e).__name__})")
            logger.error(
                "tradier_get_failed",
                extra={"event": "tradier_get_failed", "endpoint": endpoint, "error": str(e)},
            )
            raise

    # ── Options chain ─────────────────────────────────────────────────────────

    def get_option_chain(
        self,
        symbol: str,
        expiration: str,
        option_type: str = "call",
    ) -> list[dict]:
        """Full chain fetch — used for contract selection at trade entry only."""
        if not TRADIER_API_KEY:
            return []
        try:
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
                if ask == 0:
                    continue
                if (ask - bid) > MAX_BID_ASK_SPREAD:
                    continue
                if oi < MIN_OPEN_INTEREST:
                    continue
                filtered.append({
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

    # ── FIX M7: Single-contract quote (for position pricing) ─────────────────

    def get_option_quote(self, option_symbol: str) -> Optional[dict]:
        """
        Fetch bid/ask/mid for a single option contract symbol.
        Uses /markets/quotes — much cheaper than full chain fetch.
        Called every 60s while a position is open instead of the full chain.
        """
        if not TRADIER_API_KEY:
            return None
        try:
            resp = self._get("/markets/quotes", {
                "symbols": option_symbol,
                "greeks":  "false",
            })
            quotes = resp.get("quotes", {}).get("quote", {})
            if isinstance(quotes, list):
                quotes = quotes[0] if quotes else {}
            if not quotes:
                return None
            bid = float(quotes.get("bid", 0) or 0)
            ask = float(quotes.get("ask", 0) or 0)
            return {
                "symbol": option_symbol,
                "bid":    bid,
                "ask":    ask,
                "mid":    round((bid + ask) / 2, 4),
                "spread": round(ask - bid, 4),
                "last":   float(quotes.get("last", 0) or 0),
            }
        except Exception as e:
            logger.error("get_option_quote(%s) failed: %s", option_symbol, e)
            return None

    # ── Expirations ───────────────────────────────────────────────────────────

    def get_expirations(self, symbol: str) -> list[str]:
        """Return expiry dates 7–21 days out."""
        if not TRADIER_API_KEY:
            return []
        try:
            resp = self._get("/markets/options/expirations", {
                "symbol": symbol, "includeAllRoots": "true", "strikes": "false",
            })
            dates = resp.get("expirations", {}).get("date", [])
            if isinstance(dates, str):
                dates = [dates]
            today = date.today()
            result = []
            for d in dates:
                dt = date.fromisoformat(d)
                days_out = (dt - today).days
                if 7 <= days_out <= 21:
                    result.append(d)
            return result[:3]
        except Exception as e:
            logger.error("get_expirations(%s) failed: %s", symbol, e)
            return []

    # ── Orders (FIX M2b: retry wrapper) ──────────────────────────────────────

    def place_option_order(
        self,
        symbol: str,
        option_symbol: str,
        qty: int,
        side: str,          # 'buy_to_open' | 'sell_to_close'
        order_type: str = "limit",
        limit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Place an options order through Tradier brokerage.
        Uses TRADIER_ACCOUNT_ID from config (was missing before — FIX applied).
        Wraps with retry so transient network issues don't drop orders.
        """
        if not TRADIER_API_KEY or not TRADIER_ACCOUNT_ID:
            logger.warning(
                "Tradier key or account ID missing — order not sent. "
                "Set TRADIER_API_KEY and TRADIER_ACCOUNT_ID in .env"
            )
            return None

        payload = {
            "class":         "option",
            "symbol":        symbol,
            "option_symbol": option_symbol,
            "side":          side,
            "quantity":      str(qty),
            "type":          order_type,
            "duration":      "day",
        }
        if order_type == "limit" and limit_price:
            payload["price"] = str(round(limit_price, 2))

        url = f"{self.base}/accounts/{TRADIER_ACCOUNT_ID}/orders"

        def call():
            r = requests.post(url, headers=self.headers, data=payload, timeout=10)
            r.raise_for_status()
            return r.json()

        try:
            data = _retry(call)
            _oid = (data.get("order", {}) or {}).get("id", "—")
            log_event("INFO", "broker.tradier",
                      f"🟢 [{symbol}] Order confirmed by Tradier — {side.upper()} "
                      f"{qty}× {option_symbol} (order ID: {_oid}).")
            logger.info(
                "order_placed",
                extra={
                    "event": "order_placed",
                    "broker": "tradier",
                    "symbol": symbol,
                    "option_symbol": option_symbol,
                    "side": side,
                    "qty": qty,
                    "order_type": order_type,
                    "limit_price": limit_price,
                },
            )
            return data
        except Exception as e:
            log_event("ERROR", "broker.tradier",
                      f"🔴 [{symbol}] Order submission failed — {type(e).__name__}. "
                      f"No position opened.")
            logger.error(
                "order_execution_failed",
                extra={
                    "event": "order_execution_failed",
                    "broker": "tradier",
                    "symbol": symbol,
                    "option_symbol": option_symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(e),
                },
            )
            return None

    # ── Earnings ──────────────────────────────────────────────────────────────

    def get_earnings(self, symbol: str) -> list[str]:
        """
        Return upcoming earnings dates for `symbol` from Tradier.

        The /markets/fundamentals/calendars endpoint is only available on
        paid Tradier plans — it returns 404 on free/sandbox keys.
        Any HTTP 4xx is treated as "endpoint unavailable" and returns an empty
        list silently (debug-level only) so the bot isn't flooded with warnings.
        """
        # Call directly (no _retry) — this endpoint returns 404 on free Tradier
        # plans and retrying it 3× just spams the log.
        try:
            url = f"{self.base}/markets/fundamentals/calendars"
            r   = requests.get(url, headers=self.headers,
                               params={"symbols": symbol}, timeout=10)
            if r.status_code == 404 or r.status_code == 403:
                # Endpoint not available on this plan — silent, no retries.
                return []
            r.raise_for_status()
            resp   = r.json() if r.text and r.text.strip() else {}
            events = resp.get("security", {}).get("calendar", {}).get("event", [])
            if isinstance(events, dict):
                events = [events]
            return [
                e.get("date") for e in events
                if e.get("type") == "earnings" and e.get("date")
            ]
        except requests.exceptions.HTTPError as exc:
            logger.debug("get_earnings(%s): HTTP %s — skipping", symbol, exc)
            return []
        except Exception:
            return []


# ── Factory ───────────────────────────────────────────────────────────────────

def get_clients() -> tuple[AlpacaClient, TradierClient]:
    return AlpacaClient(), TradierClient()