"""
backtester/market_data.py — MarketDataMixin: _load_market_data, the
cached fetch-and-precompute pipeline (5-min/1h/15m/1-min bars, RVOL/EMA50/
ATR/ADX indicators, entry-source prep).

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.

Kept as ONE function rather than split further: it is a single ordered
fallback/precompute chain (cache check -> Alpaca fetch -> depth-check ->
yfinance fallback -> trim -> extra-timeframe fetch -> indicator precompute
-> entry-source prep -> cache save) where each step's placement is
load-bearing and later steps read state built by earlier ones — the same
"irreducible sequential function" exception used for broker/alpaca_bars.py's
get_session_bars and trading/entry/tick.py's _tick.
"""

import logging

import pandas as pd

from signals import bars_to_df, compute_rvol
from regime_manager import compute_adx_series
import backtest_data_cache

logger = logging.getLogger("celo_trader.backtester")


class MarketDataMixin:

    # ── Market data fetch + precompute (cached, see backtest_data_cache.py) ───

    def _load_market_data(self):
        """
        Fetch 5-min/1h/15m/1-min bars, precompute indicators (RVOL/EMA50/ATR/
        ADX), and prep the entry-detection sources — OR, on a same-day cache
        hit, skip all of that and restore it from disk in milliseconds.

        WHY CACHED (2026-07-22): A/B test scripts construct a fresh Backtester
        per ticker, once per variant (4-5x per run). The candles don't change
        between variants — only the strategy logic does — so re-fetching and
        re-computing indicators on identical data every variant was pure
        waste. See backtest_data_cache.py's module docstring.

        Returns either the precomputed df (success) or {"error": ...} (same
        failure cases the old inline code returned early on).
        """
        # FIX 2026-07-23: key the cache by the EFFECTIVE fetch window, not the
        # raw `months` value — see backtest_data_cache.py's module docstring.
        # months=2 and months=3 (and any months>=2) both resolve to the same
        # 59-day yfinance cap below, so they now share one cache entry instead
        # of each script re-fetching identical candles under a different key.
        import datetime as _dt
        _anchor_date = self.end_date or _dt.date.today()
        _cache_max_days = backtest_data_cache.max_days_for(self.months)
        bundle = backtest_data_cache.load(self.ticker, _cache_max_days, as_of=_anchor_date)
        if bundle is not None:
            self._df_1h        = bundle["df_1h"]
            self._df_15m       = bundle["df_15m"]
            self._df1m         = bundle["df1m"]
            self._1m_day_start = bundle["day1m_start"]
            self._df5m_full    = bundle["df5m_full"]
            self._5m_day_start = bundle["day5m_start"]
            return bundle["df"]

        # ── Fetch historical 5-min bars ───────────────────────────────────────
        # FIX 2026-07-31 (backtest speed/reliability): Alpaca is now tried
        # FIRST, yfinance is the fallback — this used to be the other way
        # around. Reasoning: Alpaca is what live trading already uses every
        # day, its requests all carry a real, working 10s timeout (broker.py's
        # _get()), and it has no 60-day depth cap the way yfinance's 5-min
        # bars do. yfinance (via curl_cffi) has caused two real incidents —
        # a hard network refusal in one environment, and a 16+ minute silent
        # hang on the user's Mac that didn't even respond to Ctrl+C (see the
        # ThreadPoolExecutor fix above/below). It's kept as a fallback only,
        # not removed, in case Alpaca's free IEX feed is ever missing a bar.
        _today    = _anchor_date
        _max_days = min(self.months * 30, 59)   # yfinance 5m hard limit = 60 d — Alpaca has no such cap
        _start_d  = (_today - _dt.timedelta(days=_max_days)).strftime("%Y-%m-%d")
        _end_d    = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        df = pd.DataFrame()
        _data_source = None
        try:
            raw = self.alpaca.get_bars(self.ticker, "5Min", limit=10000)
            bars_5m = raw[0] if isinstance(raw, tuple) else raw
            if bars_5m:
                df = bars_to_df(bars_5m)
                if not df.empty:
                    # DEPTH CHECK (2026-07-31): a non-empty result isn't the
                    # same as a COMPLETE one. Alpaca's free IEX feed has a
                    # known quirk of sometimes returning only recent bars
                    # (see broker.py get_session_bars()'s "sometimes returns
                    # only recent bars" comment, a same-day version of this
                    # same risk) — if that happens here too, treating any
                    # non-empty df as "good" would silently run the backtest
                    # over a shorter, wrong window instead of the requested
                    # one. Require the earliest returned bar to be within
                    # 20% of the requested start date; otherwise the data is
                    # too shallow and yfinance takes over instead.
                    _earliest = df["time"].min().date()
                    _latest   = df["time"].max().date()
                    _requested_start = _dt.date.fromisoformat(_start_d)
                    _slack_days = max(3, int(_max_days * 0.20))
                    # FIX 2026-08-01: this only ever checked the EARLIEST bar
                    # against the requested start — it never checked whether
                    # the data reached all the way to TODAY. Free-tier IEX can
                    # return a real, non-empty, correctly-starting range that
                    # still stops well short of the present (archived history
                    # up to some point, then a gap before the recent rolling
                    # window resumes) — get_bars()'s pagination fix (same day)
                    # made this gap visible for the first time; previously the
                    # code silently ran the backtest over whatever shorter
                    # window it got. Requiring the LATEST bar to be within the
                    # same slack window of "today" closes that gap the same
                    # way the earliest-bar check already covers the start.
                    _today_for_check = _dt.date.today()
                    if _earliest > _requested_start + _dt.timedelta(days=_slack_days):
                        logger.warning(
                            "Backtest: Alpaca 5m data for %s only goes back to %s "
                            "(requested %s) — too shallow, falling back to yfinance",
                            self.ticker, _earliest, _start_d,
                        )
                        df = pd.DataFrame()
                    elif _latest < _today_for_check - _dt.timedelta(days=_slack_days):
                        logger.warning(
                            "Backtest: Alpaca 5m data for %s stops at %s "
                            "(requested through %s) — doesn't reach recent data, "
                            "falling back to yfinance",
                            self.ticker, _latest, _end_d,
                        )
                        df = pd.DataFrame()
                    else:
                        _data_source = "alpaca"
                        logger.info("Backtest: Alpaca returned %d 5m bars for %s (%s to %s)",
                                    len(df), self.ticker, _earliest, _latest)
        except Exception as _al_ex:
            logger.warning("Backtest: Alpaca 5m fetch failed for %s: %s", self.ticker, _al_ex)

        # yfinance fallback — same 20/30s non-blocking timeout pattern as
        # _fetch_extra_timeframe() below (shutdown(wait=False) so a hang
        # can't block the process even here).
        if df.empty:
            try:
                import yfinance as yf
                import concurrent.futures as _cf

                def _do_download():
                    return yf.download(
                        self.ticker,
                        start=_start_d,
                        end=_end_d,
                        interval="5m",
                        progress=False,
                        auto_adjust=True,
                    )

                _ex = _cf.ThreadPoolExecutor(max_workers=1)
                _fut = _ex.submit(_do_download)
                try:
                    _raw_yf = _fut.result(timeout=30)
                except _cf.TimeoutError:
                    logger.warning("Backtest: yfinance timed out after 30s for %s", self.ticker)
                    _raw_yf = pd.DataFrame()
                _ex.shutdown(wait=False)

                if not _raw_yf.empty:
                    if hasattr(_raw_yf.columns, "get_level_values"):
                        _raw_yf.columns = _raw_yf.columns.get_level_values(0)
                    _raw_yf = _raw_yf.rename(columns={
                        "Open": "open", "High": "high",
                        "Low": "low", "Close": "close", "Volume": "volume",
                    })
                    _raw_yf.index.name = "time"
                    _raw_yf = _raw_yf.reset_index()
                    _raw_yf["time"] = (
                        pd.to_datetime(_raw_yf["time"], utc=True)
                        .dt.tz_convert("America/New_York")
                        .dt.tz_localize(None)
                    )
                    df = _raw_yf[["time", "open", "high", "low", "close", "volume"]].copy()
                    _data_source = "yfinance"
                    logger.info(
                        "Backtest: yfinance returned %d 5m bars for %s (%s → %s)",
                        len(df), self.ticker, _start_d, _end_d,
                    )
            except Exception as _yf_ex:
                logger.warning("Backtest: yfinance failed for %s: %s", self.ticker, _yf_ex)

        if df.empty:
            return {"error": f"No historical data for {self.ticker}"}
        self._data_source = _data_source or "unknown"

        # Trim to requested look-back window
        cutoff = pd.Timestamp(_anchor_date) - pd.DateOffset(months=self.months)
        df = df[df["time"] >= cutoff].reset_index(drop=True)

        if df.empty:
            return {"error": f"No bars within the last {self.months} months "
                    "(5-minute bars are limited to ~60 days; try 1–2 months)"}

        # 1h/15m fetch for the real dynamic trail multiplier (see
        # _fetch_extra_timeframe's docstring). 15m shares 5m's ~60-day yfinance
        # cap; 1h supports ~730 days so the same window is always covered.
        self._df_1h  = self._fetch_extra_timeframe("1h",  _start_d, _end_d)
        self._df_15m = self._fetch_extra_timeframe("15m", _start_d, _end_d)
        logger.info(
            "Backtest: extra-timeframe fetch for %s — 1h=%d bars, 15m=%d bars",
            self.ticker, len(self._df_1h), len(self._df_15m),
        )

        # Pre-compute indicators across the full dataset
        df["rvol"]  = compute_rvol(df, lookback_days=10)
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        hl  = df["high"]  - df["low"]
        hcp = (df["high"]  - df["close"].shift(1)).abs()
        lcp = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        df["_date"] = df["time"].dt.date

        # ── ADX(14) series — informational only now (2026-07-21) ─────────────
        # route_signals() does its own ADX gating internally; this is kept
        # purely so the diagnostics dict can still report a chop-bar count.
        try:
            _adx_s = compute_adx_series(df)
            if _adx_s is not None:
                df["adx"] = _adx_s.reindex(df["time"].dt.floor("5min")).to_numpy()
        except Exception as _adx_ex:
            logger.debug("ADX series unavailable: %s", _adx_ex)

        # ── Entry-detection sources (2026-07-21 integration) ─────────────────
        # Full multi-day 5-min frame, session-filtered, for the fallback path;
        # fetch_1min_entry_data() inside handles the 1-min side. See
        # _prep_entry_sources()'s docstring for why this exists.
        _full_session_mask = (
            (df["time"].dt.hour > 9) |
            ((df["time"].dt.hour == 9) & (df["time"].dt.minute >= 30))
        ) & (df["time"].dt.hour < 16)
        self._prep_entry_sources(df[_full_session_mask].reset_index(drop=True))

        backtest_data_cache.save(
            self.ticker, _cache_max_days, as_of=_anchor_date,
            df=df, df_1h=self._df_1h, df_15m=self._df_15m,
            df1m=self._df1m, day1m_start=self._1m_day_start,
            df5m_full=self._df5m_full, day5m_start=self._5m_day_start,
        )
        return df
