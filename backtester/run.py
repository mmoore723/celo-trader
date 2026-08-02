"""
backtester/run.py — RunMixin: run(), the public entry point that loads
market data, iterates trading days, and delegates each day to _simulate_day.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

import logging

from signals import compute_vwap_bands
from backtester.helpers import _quiet_router_logging

logger = logging.getLogger("celo_trader.backtester")


class RunMixin:

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        """Execute the full multi-strategy backtest. Returns a results dict."""
        logger.info(
            "backtest_start",
            extra={
                "event":        "backtest_start",
                "ticker":       self.ticker,
                "months":       self.months,
                "capital":      self.capital,
                "risk_pct":     self.risk_pct_override,
            },
        )

        df = self._load_market_data()
        if isinstance(df, dict):   # error case — see _load_market_data()
            return df

        # The dashboard's start/end dates are a contract, not a rough month
        # hint. Keep earlier bars available in the prepared sources for RVOL
        # warmup, but replay and report only the requested inclusive window.
        if self.start_date is not None:
            df = df[df["_date"] >= self.start_date].reset_index(drop=True)
        if self.end_date is not None:
            df = df[df["_date"] <= self.end_date].reset_index(drop=True)
        if df.empty:
            return {"error": "No market bars exist in the requested date range."}
        if self.start_date is not None:
            earliest = min(df["_date"])
            # Do not silently grade a shortened training period when the
            # requested range begins outside the provider's rolling intraday
            # history.  A small allowance covers weekends and market holidays.
            if earliest > self.start_date and (earliest - self.start_date).days > 3:
                return {
                    "error": (
                        f"Historical data begins on {earliest.isoformat()}, after the requested "
                        f"start date {self.start_date.isoformat()}. No result was calculated."
                    )
                }
        if self.end_date is not None:
            latest = max(df["_date"])
            # Weekends/holidays are normal, but data ending several sessions
            # before the selected end date is incomplete, not a valid test.
            if latest < self.end_date and (self.end_date - latest).days > 3:
                return {
                    "error": (
                        f"Historical data ends on {latest.isoformat()}, before the requested "
                        f"end date {self.end_date.isoformat()}. No result was calculated."
                    )
                }

        balance      = self.capital
        daily_pnl: dict[str, float] = {}

        unique_days = sorted(df["_date"].unique())
        progress = getattr(self, "_progress_callback", None)
        if callable(progress):
            progress(0, len(unique_days))

        # Diagnostic counters — returned in error message when no trades fire
        self._diag = {
            "data_source":    getattr(self, "_data_source", "unknown"),
            "total_bars":     len(df),
            "trading_days":   len(unique_days),
            "raw_signals":    0,   # bars where at least one strategy returned a Signal
            "below_floor":    0,   # signals filtered by 0.78 confidence floor
            "conflict_veto":  0,   # killed by conflict veto
            "direction_skip": 0,   # wrong direction (calls_only / puts_only)
            "no_contracts":   0,   # sized to 0 contracts
            "max_confidence": 0.0, # highest confidence seen (key: are we near the 0.78 floor?)
            "rvol_samples":   [],  # small sample of RVOL values for debugging
            "chop_bars":      0,   # bars where ADX<25 — gated strategies never evaluated at all
            "rr_gate_blocked": 0,  # passed every other gate but failed the R:R minimum (2026-07-22)
        }

        with _quiet_router_logging():
            for day_index, trade_date in enumerate(unique_days, start=1):
                day_all = df[df["_date"] == trade_date].reset_index(drop=True)
                session_mask = (
                    (day_all["time"].dt.hour > 9) |
                    ((day_all["time"].dt.hour == 9) & (day_all["time"].dt.minute >= 30))
                ) & (day_all["time"].dt.hour < 16)
                day_df  = day_all[session_mask].reset_index(drop=True)
                day_str = trade_date.isoformat()

                # VWAP must stay precomputed on day_df — backtest_exit_sim.py's
                # exit engine reads bar["vwap"] every bar (vwap+trend-dead
                # check). This is exit-side, unrelated to the entry-detection
                # change above — do not remove.
                try:
                    _vb = compute_vwap_bands(day_df, num_stds=(1, 2))
                    day_df = day_df.copy()
                    day_df["vwap"]        = _vb["vwap"].ffill()
                    day_df["vwap_upper1"] = _vb["vwap_upper1"].ffill()
                    day_df["vwap_lower1"] = _vb["vwap_lower1"].ffill()
                    day_df["vwap_upper2"] = _vb["vwap_upper2"].ffill()
                    day_df["vwap_lower2"] = _vb["vwap_lower2"].ffill()
                except Exception:
                    pass

                pnl = self._simulate_day(day_df, balance, day_str)
                balance += pnl
                if pnl != 0:
                    daily_pnl[day_str] = pnl
                if callable(progress):
                    progress(day_index, len(unique_days))

        return self._compute_results(daily_pnl, balance)
