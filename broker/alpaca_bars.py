"""
broker/alpaca_bars.py — AlpacaBarsMixin: OHLCV bar/quote/snapshot fetching.

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Alpaca*Mixin classes
into AlpacaClient in broker/alpaca_client.py.

get_session_bars is kept as ONE function rather than split further: it is a
single ordered fallback chain (session window -> IEX retry -> regular-hours
window -> previous day -> plain limit fetch -> yfinance) where each attempt's
placement in the sequence is load-bearing, the same "irreducible sequential
function" pattern used for trading/entry/tick.py's _tick and
trading/position_manager/manage.py's _manage_open_position. Splitting its
body across files would risk subtly changing the fallback order rather than
just moving code.
"""

import logging
from typing import Optional

from database import log_event
from broker.common import _AlpacaCircuitOpenError

logger = logging.getLogger("celo_trader.broker")


class AlpacaBarsMixin:

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
        params = {"timeframe": tf, "limit": limit, "adjustment": "split", "feed": "iex"}
        if tf == "1Day":
            start = (_dt.datetime.utcnow() - _dt.timedelta(days=180)).strftime("%Y-%m-%d")
            params["start"] = start
        else:
            # FIX 2026-06-20: intraday timeframes (5Min/15Min/1Hour) had NO start
            # date at all — Alpaca's implicit default window without one is too
            # FIX 2026-07-21: "1Min" was missing from this map entirely, silently
            # falling back to the 78/day default (5Min's rate) — 5x too low. A
            # limit=10000 request then computed a start date ~209 days back
            # instead of ~26, so Alpaca returned the FIRST 10000 bars from 209
            # days ago (an old, essentially random window) instead of anything
            # recent. Found via diag_1min_data_availability.py while checking
            # 1-minute data depth for a backtester resolution-fidelity fix.
            _bars_per_day = {"1Min": 390, "5Min": 78, "15Min": 26, "1Hour": 7}.get(tf, 78)
            _trading_days_needed = max(1, -(-limit // _bars_per_day))  # ceil division
            # Pad 1.6x for weekends/holidays, plus a flat 5-day floor so small
            # `limit` requests still get a sane minimum lookback window.
            _calendar_days_back = max(5, int(_trading_days_needed * 1.6) + 3)
            start = (_dt.datetime.utcnow() - _dt.timedelta(days=_calendar_days_back)).strftime("%Y-%m-%d")
            params["start"] = start

        try:
            # FIX 2026-08-01: Alpaca's bars endpoint paginates — a single
            # response can stop far short of `limit` and include a
            # next_page_token pointing at more data. This was never
            # followed, so any request whose true result spanned more than
            # one page silently returned only the FIRST page and stopped
            # there — found via a live 1-month backtest request coming back
            # with only ~2200 of the requested 10000 bars, stalled 6 months
            # before "today" instead of reaching it. Loop until no token is
            # left or we've collected `limit` bars; 20-page hard cap so a
            # pagination bug on Alpaca's end can't spin this forever.
            bars: list[dict] = []
            page_params = dict(params)
            for _ in range(20):
                resp = self._get(url, page_params)
                # FIX 2026-06-20: resp.get("bars", []) only applies the [] default when
                # the "bars" KEY IS MISSING. Alpaca can return the key present with a
                bars.extend(resp.get("bars") or [])
                _token = resp.get("next_page_token")
                if not _token or len(bars) >= limit:
                    break
                page_params = dict(params, page_token=_token)
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
        # Pull the previous day's full extended session (04:00-20:00) for gap calc.
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

    def get_latest_option_quote(self, symbol: str) -> Optional[dict]:
        """Return Alpaca's latest bid/ask for one OCC option contract.

        Contract selection currently uses Tradier, while the order is routed
        to Alpaca.  Requoting the exact contract at the execution broker keeps
        a stale/cross-provider ask from becoming an unfillable limit order.
        Alpaca's endpoint returns a mapping under ``quotes`` even for one
        requested symbol.
        """
        url = f"{self.data}/v1beta1/options/quotes/latest"
        try:
            payload = self._get(url, params={"symbols": symbol}) or {}
            quotes = payload.get("quotes") or {}
            return quotes.get(symbol) or quotes.get(symbol.upper())
        except Exception as e:
            logger.error("get_latest_option_quote(%s) failed: %s", symbol, e)
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
