"""
backtester.py — Full-Strategy Historical Simulation Engine.

Architecture
────────────
Replays N months of historical 5-min OHLCV bars through ALL 8 live strategy
modules — the same evaluate() functions the live bot uses — so backtest results
reflect what the bot would actually do, not just one strategy in isolation.

Strategies simulated
────────────────────
  INST_ORB   — Opening Range Breakout
  BOS_MSS    — Break of Structure / Market Structure Shift
  VWAP_PB    — VWAP Pullback
  FVG        — Fair Value Gap
  MID_BRK    — Midday Breakout
  AFT_REV    — After-hours Reversal
  TREND_CONT — Trend Continuation
  CHAN_BREAK  — Channel Breakout

Trade mechanics
────────────────
  Signal  : All 8 evaluate() functions run bar-by-bar; highest-confidence fires
  Sizing  : Dollar-based 1% risk model — position_$ = equity × 0.01 / stop_pct
  Options : Weekly contracts (5 DTE), ticker-specific IV (not a fixed 0.60)
  Stop    : 20% of option premium (hard, tightens dynamically every 15 min)
  Stage 1 : Sell 50% of position when premium ≥ entry × 1.50
  Stage 2 : Hold remainder; exit at break-even or time-box
  Time-box: 45 minutes from entry
  Fills   : Entry at ask (+5% slippage), exit at bid (−5% slippage)

Output
──────
- Overall P&L / win rate / Sharpe / drawdown
- Per-strategy breakdown: trades / win rate / P&L
- Daily P&L / exit reason breakdown / trade log
"""

import logging
import math
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import BACKTEST_MONTHS, STARTING_CAPITAL
from signals import (
    bars_to_df, compute_vwap_bands, compute_rvol,
    get_opening_range, ORB_RVOL_THRESHOLD,
)
from risk import RiskManager

logger = logging.getLogger("celo_trader.backtester")


# ── Per-ticker implied volatility lookup ──────────────────────────────────────
# Approximate annualised IV for each ticker.  Weekly contracts are priced on
# the market's expected move, not a fixed 0.60 that overstates SPY by 3-4×.
# Values are conservative mid-range estimates; true IV fluctuates daily.

_TICKER_IV: dict[str, float] = {
    # Index ETFs — low IV
    "SPY":  0.14,
    "QQQ":  0.18,
    "IWM":  0.22,
    "DIA":  0.14,
    # Mega-cap tech — moderate IV
    "AAPL": 0.28,
    "MSFT": 0.26,
    "AMZN": 0.32,
    "GOOGL":0.30,
    "GOOG": 0.30,
    "META": 0.38,
    "NFLX": 0.42,
    # High-volatility tech / growth
    "NVDA": 0.60,
    "AMD":  0.55,
    "TSLA": 0.72,
    "COIN": 0.85,
    "MSTR": 0.90,
    "PLTR": 0.65,
    "HOOD": 0.75,
    # Financials
    "JPM":  0.24,
    "GS":   0.28,
    "BAC":  0.28,
    # Default for unlisted tickers
    "_default": 0.40,
}


def _get_iv(ticker: str) -> float:
    return _TICKER_IV.get(ticker.upper(), _TICKER_IV["_default"])


# ── Simplified option pricer ──────────────────────────────────────────────────

def _estimate_option_price(
    stock_price: float,
    strike: float,
    days_to_expiry: int = 5,       # weekly contracts (default)
    iv: float = 0.40,
    option_type: str = "call",
) -> float:
    """
    Simplified Black-Scholes estimate (intrinsic + time value).
    time_value ≈ stock × iv × sqrt(dte/252) × 0.4
    Uses realistic per-ticker IV instead of a fixed 0.60 for all symbols.
    """
    if days_to_expiry <= 0:
        return max(0.0, stock_price - strike) if option_type == "call" \
               else max(0.0, strike - stock_price)

    intrinsic = (max(0.0, stock_price - strike) if option_type == "call"
                 else max(0.0, strike - stock_price))
    time_val  = stock_price * iv * math.sqrt(days_to_expiry / 252) * 0.4
    return round(max(intrinsic + time_val, 0.01), 2)


def _simulated_strike(stock_price: float, direction: str) -> float:
    """First OTM strike, rounded to nearest $0.50 increment."""
    if direction == "bullish":
        return math.ceil(stock_price * 2) / 2
    return math.floor(stock_price * 2) / 2


# ── Backtest engine ───────────────────────────────────────────────────────────

class Backtester:
    """
    Runs ALL 8 live strategy modules on historical 5-min bars.

    Parameters
    ----------
    alpaca           : AlpacaClient (or any object with .get_bars())
    ticker           : stock symbol to test
    months           : look-back period in months
    starting_capital : initial simulated account balance
    direction        : "both" | "calls_only" | "puts_only"
    """

    # Mirror the constants from RiskManager so they're always in sync
    ORB_STOP_PCT          = RiskManager.ORB_STOP_PCT
    ORB_RISK_PCT          = RiskManager.ORB_RISK_PCT
    ORB_STAGE1_GAIN       = RiskManager.ORB_STAGE1_GAIN
    ORB_TIME_BOX          = RiskManager.ORB_TIME_BOX
    SLIPPAGE_PCT          = RiskManager.SLIPPAGE_PCT
    STOP_TIGHTEN_INTERVAL = RiskManager.STOP_TIGHTEN_INTERVAL
    STOP_TIGHTEN_STEP     = RiskManager.STOP_TIGHTEN_STEP
    STOP_FLOOR_PCT        = RiskManager.STOP_FLOOR_PCT

    def __init__(
        self,
        alpaca,
        ticker: str,
        months: int = BACKTEST_MONTHS,
        starting_capital: float = STARTING_CAPITAL,
        direction: str = "both",
    ):
        self.alpaca    = alpaca
        self.ticker    = ticker
        self.months    = months
        self.capital   = starting_capital
        self.direction = direction
        self.trades: list[dict] = []

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute the full multi-strategy backtest.
        Returns a results dict consumed by the dashboard.
        """
        logger.info(
            "backtest_start",
            extra={
                "event":   "backtest_start",
                "ticker":  self.ticker,
                "months":  self.months,
                "capital": self.capital,
            },
        )

        # ── Fetch historical 5-min bars ───────────────────────────────────────
        # Primary: yfinance — free, reliable, 60-day max for 5-min intervals.
        # Fallback: Alpaca — IEX free tier has limited intraday history and is
        #   subject to the circuit breaker; useful as a secondary source only.
        #
        # yfinance 5-min bar cap: ~59 days.  For requests beyond 2 months the
        # backtest will use the available ~59-day window (still meaningful).
        import datetime as _dt
        _today   = _dt.date.today()
        _max_days = min(self.months * 30, 59)   # yfinance 5m hard limit = 60 d
        _start_d = (_today - _dt.timedelta(days=_max_days)).strftime("%Y-%m-%d")
        _end_d   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        df = pd.DataFrame()
        try:
            import yfinance as yf
            import concurrent.futures as _cf
            # Wrap yf.download in a thread with a 30-second timeout.
            # Without this, Yahoo Finance network hangs block the API thread
            # indefinitely — the browser spinner never resolves.
            def _do_download():
                return yf.download(
                    self.ticker,
                    start=_start_d,
                    end=_end_d,
                    interval="5m",
                    progress=False,
                    auto_adjust=True,
                )
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(_do_download)
                try:
                    _raw_yf = _fut.result(timeout=30)
                except _cf.TimeoutError:
                    logger.warning("Backtest: yfinance download timed out after 30s for %s", self.ticker)
                    _raw_yf = pd.DataFrame()
            if not _raw_yf.empty:
                # Flatten MultiIndex columns (yfinance ≥ 0.2)
                if hasattr(_raw_yf.columns, "get_level_values"):
                    _raw_yf.columns = _raw_yf.columns.get_level_values(0)
                _raw_yf = _raw_yf.rename(columns={
                    "Open": "open", "High": "high",
                    "Low": "low", "Close": "close", "Volume": "volume",
                })
                _raw_yf.index.name = "time"
                _raw_yf = _raw_yf.reset_index()
                # Convert tz-aware timestamps → ET tz-naive (matches bar_to_df format)
                _raw_yf["time"] = (
                    pd.to_datetime(_raw_yf["time"], utc=True)
                    .dt.tz_convert("America/New_York")
                    .dt.tz_localize(None)
                )
                df = _raw_yf[["time", "open", "high", "low", "close", "volume"]].copy()
                logger.info(
                    "Backtest: yfinance returned %d 5m bars for %s (%s → %s)",
                    len(df), self.ticker, _start_d, _end_d,
                )
        except Exception as _yf_ex:
            logger.warning("Backtest: yfinance bars failed for %s: %s", self.ticker, _yf_ex)

        # Alpaca fallback — only used if yfinance returned nothing
        if df.empty:
            raw = self.alpaca.get_bars(self.ticker, "5Min", limit=10000)
            bars_5m = raw[0] if isinstance(raw, tuple) else raw
            if not bars_5m:
                return {"error": f"No historical data for {self.ticker}. "
                        "yfinance returned no bars and Alpaca returned nothing."}
            df = bars_to_df(bars_5m)

        if df.empty:
            return {"error": f"No historical data for {self.ticker}"}

        # Trim to requested look-back window.
        # Note: yfinance 5m bars max out at ~59 days.  If self.months > 2, the
        # backtest will cover ~59 days regardless of what was requested.
        cutoff = pd.Timestamp.now() - pd.DateOffset(months=self.months)
        df = df[df["time"] >= cutoff].reset_index(drop=True)

        if df.empty:
            return {"error": f"No bars within the last {self.months} months "
                    f"(5-minute bars are limited to ~60 days; try 1–2 months)"}

        # Pre-compute RVOL for the full dataset (needs multi-day history).
        # Strategies read today["rvol"] from each bar's slice; we inject this
        # column so it's available without re-running the 10-day rolling window
        # on every single bar (which would be extremely slow).
        df["rvol"] = compute_rvol(df, lookback_days=10)

        # Pre-compute EMA50 across the full dataset (long-term trend filter).
        # Session slices will have the correct historical EMA values.
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

        # Pre-compute ATR14 across the full dataset.
        hl  = df["high"]  - df["low"]
        hcp = (df["high"]  - df["close"].shift(1)).abs()
        lcp = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        balance      = self.capital
        daily_pnl: dict[str, float] = {}

        df["_date"]   = df["time"].dt.date
        unique_days   = sorted(df["_date"].unique())

        for trade_date in unique_days:
            day_df  = df[df["_date"] == trade_date].reset_index(drop=True)
            day_str = trade_date.isoformat()

            pnl = self._simulate_day(day_df, balance, day_str)
            balance += pnl
            if pnl != 0:
                daily_pnl[day_str] = pnl

            if daily_pnl.get(day_str, 0) < -(balance * 0.12):
                logger.debug("Backtest: daily loss limit hit on %s", day_str)

        return self._compute_results(daily_pnl, balance)

    # ── Day simulation ────────────────────────────────────────────────────────

    def _simulate_day(self, day_df: pd.DataFrame, balance: float, day_str: str) -> float:
        """
        Simulate a single trading day using all 8 strategy evaluators.

        For each bar, a slice of the current day's bars (up to that bar) is
        enriched with session-VWAP and passed to every strategy's evaluate().
        The highest-confidence signal fires; position management mirrors live
        risk.py exactly (dynamic stop, stage 1/2 exits, 45-min time-box).

        Multiple non-overlapping trades per day are allowed (once a trade
        exits, the next signal can enter).
        """
        # Import strategy modules here to avoid circular imports at module load
        import strategies.inst_orb  as _inst_orb
        import strategies.bos_mss   as _bos_mss
        import strategies.vwap_pb   as _vwap_pb
        import strategies.fvg       as _fvg
        import strategies.mid_brk   as _mid_brk
        import strategies.aft_rev   as _aft_rev
        import strategies.trend_cont as _trend_cont
        import strategies.chan_break as _chan_break
        from strategies.base import _signal_cooldown

        _EVALUATORS = [
            ("INST_ORB",   _inst_orb.evaluate),
            ("BOS_MSS",    _bos_mss.evaluate),
            ("VWAP_PB",    _vwap_pb.evaluate),
            ("FVG",        _fvg.evaluate),
            ("MID_BRK",    _mid_brk.evaluate),
            ("AFT_REV",    _aft_rev.evaluate),
            ("TREND_CONT", _trend_cont.evaluate),
            ("CHAN_BREAK",  _chan_break.evaluate),
        ]

        # Clear cooldowns at the start of each day so yesterday's cooldown
        # windows don't bleed into today's simulation.
        _signal_cooldown.clear()

        if len(day_df) < 5:
            return 0.0

        ticker_iv = _get_iv(self.ticker)

        in_trade          = False
        entry_price       = 0.0
        entry_strike      = 0.0
        entry_bar_time: Optional[pd.Timestamp] = None
        option_type       = "call"
        position_dollars  = 0.0
        remaining_dollars = 0.0
        stage1_done       = False
        session_pnl       = 0.0
        active_strategy   = "UNKNOWN"

        for idx in range(4, len(day_df)):    # need ≥ 4 bars for indicator warmup
            bar   = day_df.iloc[idx]
            close = float(bar["close"])
            ts    = bar["time"]

            # ── Manage open position ──────────────────────────────────────────
            if in_trade:
                elapsed_min = (ts - entry_bar_time).total_seconds() / 60

                # Reprice the SAME contract (fixed entry_strike)
                opt_price = _estimate_option_price(
                    close, entry_strike, 5, iv=ticker_iv, option_type=option_type,
                )

                # Dynamic stop: tightens 5pp every 15 min (mirrors live risk.py)
                elapsed_steps  = int(elapsed_min / self.STOP_TIGHTEN_INTERVAL)
                dynamic_sl_pct = max(
                    self.ORB_STOP_PCT - elapsed_steps * self.STOP_TIGHTEN_STEP,
                    self.STOP_FLOOR_PCT,
                )
                sl_price = entry_price * (1.0 - dynamic_sl_pct)

                # Hard stop
                if opt_price <= sl_price:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "stop_loss", ts.hour, round(elapsed_min, 1), active_strategy,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue   # keep scanning for next signal

                # Stage 1: sell 50% at +50%
                if not stage1_done:
                    s1_price = entry_price * (1.0 + self.ORB_STAGE1_GAIN)
                    if opt_price >= s1_price:
                        s1_exit_px   = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                        half_dollars = position_dollars / 2.0
                        s1_pnl = half_dollars * ((s1_exit_px / entry_price) - 1.0)
                        session_pnl += s1_pnl
                        self.trades.append({
                            "strategy_id":     active_strategy,
                            "option_type":     option_type,
                            "entry_price":     entry_price,
                            "exit_price":      s1_exit_px,
                            "position_dollars": half_dollars,
                            "pnl":             s1_pnl,
                            "exit_reason":     "stage1_50pct",
                            "entry_hour":      entry_bar_time.hour,
                            "held_minutes":    round(elapsed_min, 1),
                        })
                        remaining_dollars = half_dollars
                        stage1_done       = True
                        continue

                # Stage 2: break-even stop on remainder
                if stage1_done and opt_price <= entry_price:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "stage2_break_even", ts.hour, round(elapsed_min, 1), active_strategy,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                # 45-minute time-box
                if elapsed_min >= self.ORB_TIME_BOX:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "time_box_45m", ts.hour, round(elapsed_min, 1), active_strategy,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                continue   # still holding

            # ── Signal detection: run all 8 strategy evaluators ───────────────
            # Build a slice of today's bars up to the current bar (no lookahead).
            # RVOL, EMA50, ATR are pre-computed on the full dataset and already
            # present as columns; we only need to compute session-VWAP here.
            bar_slice = day_df.iloc[: idx + 1].copy()

            # Session VWAP (resets at market open, correct per-bar)
            try:
                vwap_frame = compute_vwap_bands(bar_slice, num_stds=(1, 2))
                bar_slice["vwap"]        = vwap_frame["vwap"].ffill()
                bar_slice["vwap_upper1"] = vwap_frame["vwap_upper1"].ffill()
                bar_slice["vwap_lower1"] = vwap_frame["vwap_lower1"].ffill()
                bar_slice["vwap_upper2"] = vwap_frame["vwap_upper2"].ffill()
                bar_slice["vwap_lower2"] = vwap_frame["vwap_lower2"].ffill()
            except Exception:
                continue   # malformed bar data — skip

            # vol_sma20 (100-bar rolling volume mean)
            bar_slice["vol_sma20"] = (
                bar_slice["volume"].rolling(100, min_periods=5).mean()
            )

            signals = []
            for strategy_id, fn in _EVALUATORS:
                try:
                    # Pass "BT" prefix so _audit_plain_english is still called
                    # but cooldown keys are namespaced to the backtest run.
                    sig = fn(bar_slice, ticker=self.ticker)
                    if sig is not None:
                        signals.append(sig)
                except Exception:
                    pass   # never let a strategy crash the whole backtest

            if not signals:
                continue

            # Take the highest-confidence signal
            signals.sort(key=lambda s: s.confidence, reverse=True)
            signal    = signals[0]
            direction = signal.direction   # "bullish" or "bearish"
            strat_id  = signal.strategy_id

            # Direction filter
            opt_type_str = "call" if direction == "bullish" else "put"
            if self.direction == "calls_only" and opt_type_str != "call":
                continue
            if self.direction == "puts_only"  and opt_type_str != "put":
                continue

            # ── Simulate entry ────────────────────────────────────────────────
            strike      = _simulated_strike(close, direction)
            raw_opt_px  = _estimate_option_price(
                close, strike, 5, iv=ticker_iv, option_type=opt_type_str,
            )
            if raw_opt_px <= 0.0:
                continue

            entry_opt_px = round(raw_opt_px * (1.0 + self.SLIPPAGE_PCT), 4)
            if entry_opt_px <= 0.0:
                continue

            # ── Dollar-based position sizing ──────────────────────────────────
            risk_budget     = balance * self.ORB_RISK_PCT
            pos_dollars     = min(risk_budget / self.ORB_STOP_PCT, balance * 0.20)
            if pos_dollars <= 0.0:
                continue

            in_trade          = True
            entry_price       = entry_opt_px
            entry_strike      = strike
            option_type       = opt_type_str
            entry_bar_time    = ts
            position_dollars  = pos_dollars
            remaining_dollars = pos_dollars
            stage1_done       = False
            active_strategy   = strat_id

        # ── EOD: force-close any open position ───────────────────────────────
        if in_trade and remaining_dollars > 0:
            last_bar   = day_df.iloc[-1]
            last_close = float(last_bar["close"])
            eod_mid    = _estimate_option_price(
                last_close, entry_strike, 5, iv=ticker_iv, option_type=option_type,
            )
            eod_price = round(eod_mid * (1.0 - self.SLIPPAGE_PCT), 4)
            eod_time  = last_bar["time"]
            elapsed   = (eod_time - entry_bar_time).total_seconds() / 60 if entry_bar_time else 0
            pnl = self._close_bt_trade(
                entry_price, eod_price, remaining_dollars, option_type,
                "eod", eod_time.hour if not isinstance(eod_time, float) else 15,
                round(elapsed, 1), active_strategy,
            )
            session_pnl += pnl

        return session_pnl

    # ── Trade recorder ────────────────────────────────────────────────────────

    def _close_bt_trade(
        self,
        entry_price: float,
        exit_price: float,
        position_dollars: float,
        option_type: str,
        reason: str,
        entry_hour: int = 10,
        held_minutes: float = 0.0,
        strategy_id: str = "UNKNOWN",
    ) -> float:
        """Record a simulated trade and return its P&L."""
        if entry_price <= 0.0:
            return 0.0
        pnl = position_dollars * ((exit_price / entry_price) - 1.0)
        self.trades.append({
            "strategy_id":     strategy_id,
            "option_type":     option_type,
            "entry_price":     entry_price,
            "exit_price":      exit_price,
            "position_dollars": position_dollars,
            "pnl":             pnl,
            "exit_reason":     reason,
            "entry_hour":      entry_hour,
            "held_minutes":    held_minutes,
        })
        return pnl

    # ── Results aggregation ───────────────────────────────────────────────────

    def _compute_results(self, daily_pnl: dict, final_balance: float) -> dict:
        """Aggregate backtest trades into summary statistics."""
        trades = self.trades
        pnls   = [t["pnl"] for t in trades]

        if not pnls:
            return {"error": "No trades generated in backtest period"}

        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # ── Per-strategy breakdown ─────────────────────────────────────────
        # Shows which strategies are actually profitable vs which are dragging
        # down the overall result — the key insight the old ORB-only backtest
        # couldn't provide.
        strategy_stats: dict[str, dict] = {}
        for t in trades:
            sid = t.get("strategy_id", "UNKNOWN")
            if sid not in strategy_stats:
                strategy_stats[sid] = {"trades": 0, "wins": 0, "pnl": 0.0}
            strategy_stats[sid]["trades"] += 1
            strategy_stats[sid]["pnl"]    += t["pnl"]
            if t["pnl"] > 0:
                strategy_stats[sid]["wins"] += 1

        strategy_breakdown = {}
        for sid, s in strategy_stats.items():
            wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0.0
            strategy_breakdown[sid] = {
                "trades":   s["trades"],
                "wins":     s["wins"],
                "win_rate": round(wr, 1),
                "pnl":      round(s["pnl"], 2),
            }

        # ── Call vs Put breakdown ──────────────────────────────────────────
        calls     = [t for t in trades if t.get("option_type") == "call"]
        puts      = [t for t in trades if t.get("option_type") == "put"]
        call_wins = [t for t in calls if t["pnl"] > 0]
        put_wins  = [t for t in puts  if t["pnl"] > 0]

        # ── Exit reason breakdown ──────────────────────────────────────────
        exit_reasons: dict = {}
        for t in trades:
            r = t.get("exit_reason", "unknown")
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "pnl": 0.0}
            exit_reasons[r]["count"] += 1
            exit_reasons[r]["pnl"]   += t["pnl"]

        # ── Hold time ─────────────────────────────────────────────────────
        held_times = [t.get("held_minutes", 0) for t in trades if t.get("held_minutes", 0) > 0]
        avg_hold   = round(sum(held_times) / len(held_times), 1) if held_times else 0.0

        # ── Stage-1 hit rate ───────────────────────────────────────────────
        stage1_exits = [t for t in trades if t.get("exit_reason") == "stage1_50pct"]
        stage1_rate  = len(stage1_exits) / max(len(trades), 1) * 100

        # ── Consecutive losses ─────────────────────────────────────────────
        max_consec, cur_consec = 0, 0
        for p in pnls:
            if p <= 0:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec = 0

        # ── Core stats ────────────────────────────────────────────────────
        win_rate   = len(wins) / len(pnls) if pnls else 0
        avg_win    = sum(wins)   / len(wins)   if wins   else 0
        avg_loss   = sum(losses) / len(losses) if losses else 0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # Sharpe (annualised)
        daily_returns = list(daily_pnl.values())
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * math.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        equity, peak, max_dd = self.capital, self.capital, 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        return {
            "ticker":           self.ticker,
            "months":           self.months,
            "total_trades":     len(pnls),
            "win_rate":         win_rate,
            "avg_win":          avg_win,
            "avg_loss":         avg_loss,
            "total_pnl":        sum(pnls),
            "final_balance":    final_balance,
            "total_return":     (final_balance - self.capital) / self.capital * 100,
            "max_drawdown":     max_dd,
            "sharpe_ratio":     round(sharpe, 2),
            "expectancy":       round(expectancy, 2),
            "max_consec_loss":  max_consec,
            "stage1_hit_rate":  round(stage1_rate, 1),
            "avg_hold_minutes": avg_hold,
            # Call vs Put
            "call_trades":      len(calls),
            "put_trades":       len(puts),
            "call_win_rate":    round(len(call_wins) / max(len(calls), 1) * 100, 1),
            "put_win_rate":     round(len(put_wins)  / max(len(puts),  1) * 100, 1),
            "call_pnl":         round(sum(t["pnl"] for t in calls), 2),
            "put_pnl":          round(sum(t["pnl"] for t in puts),  2),
            # Per-strategy breakdown (the new key insight)
            "strategy_breakdown": strategy_breakdown,
            # Time / exit analysis
            "exit_reasons":     exit_reasons,
            "daily_pnl":        daily_pnl,
            "trades":           trades,
        }
