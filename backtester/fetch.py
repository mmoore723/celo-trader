"""
backtester/fetch.py — FetchMixin: extra-timeframe (1h/15m) bar fetch for
the dynamic ATR-trail multiplier, and entry-detection source prep (1-min
where available, 5-min fallback elsewhere).

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

import logging

import pandas as pd

from signals import bars_to_df
from backtester.one_minute_data import fetch_1min_entry_data

logger = logging.getLogger("celo_trader.backtester")


class FetchMixin:

    # ── Extra-timeframe fetch (2026-07-21, for the dynamic ATR-trail multiplier) ─
    # Live position_manager.py doesn't use a flat trail multiplier — it widens
    # or tightens the ATR trail based on 1-hour trend bias and 15-min swing
    # proximity (plus 5-min RSI/MACD, which the primary 5m `df` already
    # covers). The backtester used to skip this and use a flat 2.0x base —
    # disclosed as a known gap. This fetches those two extra timeframes so
    # backtest_exit_sim.py can replicate the REAL adaptive multiplier instead
    # of a static stand-in. Best-effort: any failure here just means the
    # trail falls back to the flat 2.0x base, same as before — never fatal.
    def _fetch_extra_timeframe(self, interval: str, start_d: str, end_d: str) -> pd.DataFrame:
        # FIX 2026-07-31 (backtest speed/reliability): Alpaca tried first —
        # same reasoning as the primary 5-min fetch above. get_bars() maps
        # "1h"/"15m" to Alpaca's "1Hour"/"15Min" and already has a real,
        # working 10s timeout. yfinance only runs if Alpaca comes back empty.
        _alpaca_tf = {"1h": "1Hour", "15m": "15Min"}.get(interval)
        if _alpaca_tf:
            try:
                raw = self.alpaca.get_bars(self.ticker, _alpaca_tf, limit=2000)
                bars = raw[0] if isinstance(raw, tuple) else raw
                if bars:
                    _df = bars_to_df(bars)
                    if not _df.empty:
                        logger.info("Backtest: Alpaca returned %d %s bars for %s",
                                    len(_df), interval, self.ticker)
                        return _df
            except Exception as _al_ex:
                logger.warning("Backtest: Alpaca %s fetch failed for %s: %s",
                                interval, self.ticker, _al_ex)

        if getattr(self.alpaca, 'feed_policy', None) == 'tradier_consolidated_v1':
            return pd.DataFrame()  # Report unavailable, never substitute another provider.
        try:
            import yfinance as yf
            import concurrent.futures as _cf

            def _do_download():
                return yf.download(
                    self.ticker, start=start_d, end=end_d,
                    interval=interval, progress=False, auto_adjust=True,
                )

            # FIX 2026-07-31: `with ThreadPoolExecutor(...)` was cosmetic here —
            # exiting the `with` block calls shutdown(wait=True), which BLOCKS
            # until the background thread actually finishes, even after the
            # .result(timeout=20) above it already timed out. If yf.download()
            # truly hangs (TCP connects but never receives data — no error, no
            # exception, just silence), the process still blocks forever on
            # exit, defeating the timeout entirely. Confirmed live: a run on
            # the user's Mac hung with no output for 16+ minutes and didn't
            # even respond to Ctrl+C (blocked in a native thread-join, not
            # Python bytecode). Managing the executor manually and calling
            # shutdown(wait=False) on timeout lets the main thread move on —
            # the stuck background thread is abandoned, not force-killed
            # (Python can't kill threads), but it no longer blocks anything.
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(_do_download)
            try:
                _raw = _fut.result(timeout=20)
            except _cf.TimeoutError:
                logger.warning("Backtest: yfinance %s timed out for %s", interval, self.ticker)
                _ex.shutdown(wait=False)
                return pd.DataFrame()
            _ex.shutdown(wait=False)

            if _raw.empty:
                return pd.DataFrame()
            if hasattr(_raw.columns, "get_level_values"):
                _raw.columns = _raw.columns.get_level_values(0)
            _raw = _raw.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            _raw.index.name = "time"
            _raw = _raw.reset_index()
            _raw["time"] = (
                pd.to_datetime(_raw["time"], utc=True)
                .dt.tz_convert("America/New_York")
                .dt.tz_localize(None)
            )
            return _raw[["time", "open", "high", "low", "close", "volume"]].copy()
        except Exception as _ex:
            logger.warning("Backtest: %s fetch failed for %s: %s", interval, self.ticker, _ex)
            return pd.DataFrame()

    # ── Entry-detection source prep (2026-07-21 integration) ─────────────────

    def _prep_entry_sources(self, df5_session: pd.DataFrame) -> None:
        """
        Prepare both possible entry-detection sources for _simulate_day():
        1-minute bars where Alpaca has coverage, and the full multi-day
        5-minute frame (session-filtered, indicators already attached) as a
        fallback for days outside that window. Both are stored as single
        sorted frames with a per-date starting row index so _simulate_day()
        can slice "all history up to now" in O(1) — needed because real
        RVOL (compute_rvol's 10-day lookback) requires multi-day context,
        not just the current day.

        WHY 1-MIN AT ALL: diag_entry_resolution_comparison.py found the
        1-min view caught a signal the 5-min view missed ENTIRELY on 8 of 17
        SPY days (47%) — a bigger, more clearly evidenced effect than any of
        the threshold tuning done earlier this session. Falling back to
        5-min for days outside Alpaca's ~18-trading-day 1-min window (see
        backtester_1min_entry.py) keeps the full backtest date range intact
        instead of shrinking every run down to 18 days.
        """
        self._df5m_full = df5_session
        self._5m_day_start = {
            d: int(grp.index[0]) for d, grp in df5_session.groupby("_date")
        }

        self._df1m = None
        self._1m_day_start = {}
        try:
            raw = fetch_1min_entry_data(self.alpaca, self.ticker, months=self.months)
            if raw is None or raw.empty:
                logger.info("Backtest: no 1-min data for %s — every day uses 5-min entries", self.ticker)
                return
            mask = (
                (raw["time"].dt.hour > 9) |
                ((raw["time"].dt.hour == 9) & (raw["time"].dt.minute >= 30))
            ) & (raw["time"].dt.hour < 16)
            df1m = raw[mask].sort_values("time").reset_index(drop=True)
            if df1m.empty:
                return
            self._1m_day_start = {
                d: int(grp.index[0]) for d, grp in df1m.groupby("_date")
            }
            self._df1m = df1m
            logger.info(
                "Backtest: 1-min entry data for %s — %d bars across %d days "
                "(5-min fallback for the rest)",
                self.ticker, len(df1m), len(self._1m_day_start),
            )
        except Exception as ex:
            logger.warning(
                "1-min entry fetch failed for %s (%s) — every day uses 5-min entries",
                self.ticker, ex,
            )
