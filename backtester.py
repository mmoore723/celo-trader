"""
backtester.py — Full-Strategy Historical Simulation Engine.

Architecture
────────────
Replays N months of historical 5-min OHLCV bars through ALL 8 live strategy
modules using the SAME quality gates the live bot applies:
  • 78% confidence floor  (strategy_router._MIN_CONFIDENCE)
  • Conflict veto         (strategy_router._CONFLICT_VETO_BAND)
  • Contract-based sizing (risk.RiskManager.calculate_contracts — same 4-tier ladder)
  • Matched exit logic    (early momentum stop, stage-2 floor, 30/90-min time caps)

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

Trade mechanics (now mirroring live bot)
────────────────────────────────────────
  Signal  : All 8 evaluate() run; filtered by confidence floor + conflict veto
  Sizing  : calculate_contracts() — same 4-tier risk ladder as live bot
            Optional risk_pct override lets you test any flat rate
  Options : Weekly contracts (5 DTE), ticker-specific IV
  Stop    : 20% hard stop, tightened dynamically every 15 min (floor 10%)
  Early   : −EARLY_STOP_PCT (12%) within first EARLY_TIMEBOX_MIN window
  Stage 1 : Sell 50% of contracts at +50% premium gain
  Stage 2 : Trailing stop floor at entry × (1 + STAGE2_TRAIL_PCT = 1.15)
  Time-box: momentum_dead_exit fires early if RVOL < 1.0 AND losing AND ≥ 15 min
            60 min hard cap for flat/losing (extended from 30 min)
            90 min for winners (stage1 IS done) — ORB_TIME_BOX_WINNER
  Fills   : Entry at ask (+5% slippage), exit at bid (−5% slippage)

Output
──────
- Overall P&L / win rate / Sharpe / drawdown
- Per-strategy breakdown
- Daily P&L / exit reason breakdown / trade log (with contract counts)
"""

import logging
import math
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    BACKTEST_MONTHS, STARTING_CAPITAL,
    EARLY_TIMEBOX_MIN, EARLY_STOP_PCT, STAGE2_TRAIL_PCT,
    MOMENTUM_DEAD_RVOL, MOMENTUM_DEAD_MIN,
)
from signals import (
    bars_to_df, compute_vwap_bands, compute_rvol,
    get_opening_range, ORB_RVOL_THRESHOLD,
)
from risk import RiskManager

# Router quality-gate constants — import directly so the backtester
# always stays in sync when these values are tuned in strategy_router.py
from strategy_router import _MIN_CONFIDENCE, _CONFLICT_VETO_BAND, _SESSION_BIAS_PENALTY

logger = logging.getLogger("celo_trader.backtester")


# ── Per-ticker implied volatility lookup ──────────────────────────────────────
# Approximate annualised IV for each ticker.  Weekly contracts are priced on
# the market's expected move, not a fixed 0.60 that overstates SPY by 3-4×.
_TICKER_IV: dict[str, float] = {
    "SPY":  0.14, "QQQ":  0.18, "IWM":  0.22, "DIA":  0.14,
    "AAPL": 0.28, "MSFT": 0.26, "AMZN": 0.32, "GOOGL":0.30,
    "GOOG": 0.30, "META": 0.38, "NFLX": 0.42,
    "NVDA": 0.60, "AMD":  0.55, "TSLA": 0.72, "COIN": 0.85,
    "MSTR": 0.90, "PLTR": 0.65, "HOOD": 0.75,
    "JPM":  0.24, "GS":   0.28, "BAC":  0.28,
    "_default": 0.40,
}


def _get_iv(ticker: str) -> float:
    return _TICKER_IV.get(ticker.upper(), _TICKER_IV["_default"])


# ── Simplified option pricer ──────────────────────────────────────────────────

def _estimate_option_price(
    stock_price: float,
    strike: float,
    days_to_expiry: int = 5,
    iv: float = 0.40,
    option_type: str = "call",
) -> float:
    """
    Simplified Black-Scholes estimate with OTM moneyness discount.

    For ATM options: time_value ≈ stock × iv × sqrt(dte/252) × 0.4
    For OTM options: time_value decays via erfc as the strike moves away from
    the stock price, normalized by the 1-sigma expected move.  This reflects
    that a $3 OTM weekly costs less than a $6 ATM weekly even though both have
    zero intrinsic value — the ATM-only formula was overstating option costs
    by 2-3× and blocking valid contract sizing at small account balances.
    """
    if days_to_expiry <= 0:
        return max(0.0, stock_price - strike) if option_type == "call" \
               else max(0.0, strike - stock_price)

    intrinsic = (max(0.0, stock_price - strike) if option_type == "call"
                 else max(0.0, strike - stock_price))

    sqrt_t        = math.sqrt(days_to_expiry / 252)
    expected_move = stock_price * iv * sqrt_t            # 1-sigma expected move

    # Distance the strike sits OTM (0 for ITM/ATM options)
    otm_dist = (max(0.0, strike - stock_price) if option_type == "call"
                else max(0.0, stock_price - strike))

    # Normalize by expected move; erfc gives 1.0 at-the-money, decays to 0 deep OTM.
    # erfc(x * 1/√2) approximates 2·N(-x) which is the standard moneyness decay.
    otm_z            = otm_dist / max(expected_move, 0.01)
    moneyness_factor = math.erfc(otm_z * 0.7071)        # 0.7071 = 1/√2

    time_val = stock_price * iv * sqrt_t * 0.4 * moneyness_factor
    return round(max(intrinsic + time_val, 0.01), 2)


# OTM offset used when simulating strikes — 1.5% from the current stock price.
# The live bot buys weekly OTM options in the $2–4 range; the old "first $0.50
# above stock" was essentially ATM on high-price tickers (SPY $732 → $732.50),
# which inflated the model price to ~$5.78 and blocked sizing at small balances.
_SIMULATED_OTM_PCT: float = 0.015   # 1.5% OTM


def _simulated_strike(stock_price: float, direction: str) -> float:
    """Strike 1.5% OTM, rounded to the nearest $0.50 increment."""
    if direction == "bullish":
        return math.ceil(stock_price * (1 + _SIMULATED_OTM_PCT) * 2) / 2
    return math.floor(stock_price * (1 - _SIMULATED_OTM_PCT) * 2) / 2


# ── Backtest engine ───────────────────────────────────────────────────────────

class Backtester:
    """
    Runs ALL 8 live strategy modules on historical 5-min bars using the
    SAME entry filters and exit logic as the live trading bot.

    Parameters
    ----------
    alpaca           : AlpacaClient (or any object with .get_bars())
    ticker           : stock symbol to test
    months           : look-back period in months
    starting_capital : initial simulated account balance
    direction        : "both" | "calls_only" | "puts_only"
    risk_pct         : override risk % (e.g. 0.05 for 5%). None = use live tier ladder.
    """

    # Mirror the constants from RiskManager so they're always in sync
    ORB_STOP_PCT          = RiskManager.ORB_STOP_PCT           # 0.20
    ORB_STAGE1_GAIN       = RiskManager.ORB_STAGE1_GAIN        # 0.50
    ORB_TIME_BOX_WINNER   = RiskManager.ORB_TIME_BOX_WINNER    # 90 min
    SLIPPAGE_PCT          = RiskManager.SLIPPAGE_PCT           # 0.05
    STOP_TIGHTEN_INTERVAL = RiskManager.STOP_TIGHTEN_INTERVAL  # 15 min
    STOP_TIGHTEN_STEP     = RiskManager.STOP_TIGHTEN_STEP      # 0.05
    STOP_FLOOR_PCT        = RiskManager.STOP_FLOOR_PCT         # 0.10

    def __init__(
        self,
        alpaca,
        ticker: str,
        months: int = BACKTEST_MONTHS,
        starting_capital: float = STARTING_CAPITAL,
        direction: str = "both",
        risk_pct: Optional[float] = None,
    ):
        self.alpaca            = alpaca
        self.ticker            = ticker
        self.months            = months
        self.capital           = starting_capital
        self.direction         = direction
        self.risk_pct_override = risk_pct   # None → live 4-tier ladder
        self.trades: list[dict] = []

    # ── Contract sizing helper ────────────────────────────────────────────────

    def _size_contracts(self, balance: float, entry_px: float) -> int:
        """
        Size using live bot's contract formula.

        Replicates RiskManager.calculate_contracts() exactly, with an optional
        risk_pct override so the backtester can test any flat rate.

        Formula: floor( (balance × risk_pct) / (entry_px × ORB_STOP_PCT × 100) )
        Min 1 contract if budget allows; notional capped at 20–30% of balance.
        """
        if entry_px <= 0 or balance <= 0:
            return 0

        # Determine effective risk % — override takes priority over live tier logic
        if self.risk_pct_override is not None:
            risk_pct = float(self.risk_pct_override)
        else:
            # Use the live bot's 4-tier ladder based on current simulated balance
            _rm_temp = RiskManager(account_balance=balance)
            risk_pct = _rm_temp.effective_risk_pct(balance)

        total_risk        = balance * risk_pct
        risk_per_contract = entry_px * self.ORB_STOP_PCT * 100   # $ at risk per contract

        if risk_per_contract <= 0:
            return 0

        contracts = int(total_risk / risk_per_contract)

        # Notional cap: 30% of balance in high-risk tiers, 20% in conservative
        max_notional_pct = 0.30 if risk_pct > 0.01 else 0.20
        max_notional     = balance * max_notional_pct

        # Floor to 1 contract if we can afford the PREMIUM (notional check).
        # The risk-based floor (risk_per_contract <= total_risk) is too strict
        # for small accounts trading expensive underlyings like SPY — the live
        # bot uses real broker prices which are often cheaper than the BS model,
        # so it can enter where the model says 0.  Match that behavior here by
        # allowing 1 contract whenever 1 contract's notional fits the cap.
        if contracts == 0 and (entry_px * 100) <= max_notional:
            contracts = 1

        while contracts > 1 and (entry_px * 100 * contracts) > max_notional:
            contracts -= 1

        return max(0, contracts)

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

        # ── Fetch historical 5-min bars ───────────────────────────────────────
        import datetime as _dt
        _today    = _dt.date.today()
        _max_days = min(self.months * 30, 59)   # yfinance 5m hard limit = 60 d
        _start_d  = (_today - _dt.timedelta(days=_max_days)).strftime("%Y-%m-%d")
        _end_d    = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        df = pd.DataFrame()
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

            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(_do_download)
                try:
                    _raw_yf = _fut.result(timeout=30)
                except _cf.TimeoutError:
                    logger.warning("Backtest: yfinance timed out after 30s for %s", self.ticker)
                    _raw_yf = pd.DataFrame()

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
                logger.info(
                    "Backtest: yfinance returned %d 5m bars for %s (%s → %s)",
                    len(df), self.ticker, _start_d, _end_d,
                )
        except Exception as _yf_ex:
            logger.warning("Backtest: yfinance failed for %s: %s", self.ticker, _yf_ex)

        # Alpaca fallback
        if df.empty:
            raw = self.alpaca.get_bars(self.ticker, "5Min", limit=10000)
            bars_5m = raw[0] if isinstance(raw, tuple) else raw
            if not bars_5m:
                return {"error": f"No historical data for {self.ticker}."}
            df = bars_to_df(bars_5m)

        if df.empty:
            return {"error": f"No historical data for {self.ticker}"}

        # Trim to requested look-back window
        cutoff = pd.Timestamp.now() - pd.DateOffset(months=self.months)
        df = df[df["time"] >= cutoff].reset_index(drop=True)

        if df.empty:
            return {"error": f"No bars within the last {self.months} months "
                    "(5-minute bars are limited to ~60 days; try 1–2 months)"}

        # Pre-compute indicators across the full dataset
        df["rvol"]  = compute_rvol(df, lookback_days=10)
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        hl  = df["high"]  - df["low"]
        hcp = (df["high"]  - df["close"].shift(1)).abs()
        lcp = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        balance      = self.capital
        daily_pnl: dict[str, float] = {}

        df["_date"] = df["time"].dt.date
        unique_days = sorted(df["_date"].unique())

        # Diagnostic counters — returned in error message when no trades fire
        self._diag = {
            "data_source":    "yfinance" if not df.empty else "alpaca",
            "total_bars":     len(df),
            "trading_days":   len(unique_days),
            "raw_signals":    0,   # bars where at least one strategy returned a Signal
            "below_floor":    0,   # signals filtered by 0.78 confidence floor
            "conflict_veto":  0,   # killed by conflict veto
            "direction_skip": 0,   # wrong direction (calls_only / puts_only)
            "no_contracts":   0,   # sized to 0 contracts
            "max_confidence": 0.0, # highest confidence seen (key: are we near the 0.78 floor?)
            "rvol_samples":   [],  # small sample of RVOL values for debugging
        }

        # Import strategy modules ONCE
        import strategies.inst_orb   as _inst_orb
        import strategies.bos_mss    as _bos_mss
        import strategies.vwap_pb    as _vwap_pb
        import strategies.fvg        as _fvg
        import strategies.mid_brk    as _mid_brk
        import strategies.aft_rev    as _aft_rev
        import strategies.trend_cont as _trend_cont
        import strategies.chan_break  as _chan_break

        _EVALUATORS_CACHED = [
            ("INST_ORB",   _inst_orb.evaluate),
            ("BOS_MSS",    _bos_mss.evaluate),
            ("VWAP_PB",    _vwap_pb.evaluate),
            ("FVG",        _fvg.evaluate),
            ("MID_BRK",    _mid_brk.evaluate),
            ("AFT_REV",    _aft_rev.evaluate),
            ("TREND_CONT", _trend_cont.evaluate),
            ("CHAN_BREAK",  _chan_break.evaluate),
        ]

        for trade_date in unique_days:
            day_all = df[df["_date"] == trade_date].reset_index(drop=True)
            session_mask = (
                (day_all["time"].dt.hour > 9) |
                ((day_all["time"].dt.hour == 9) & (day_all["time"].dt.minute >= 30))
            ) & (day_all["time"].dt.hour < 16)
            day_df  = day_all[session_mask].reset_index(drop=True)
            day_str = trade_date.isoformat()

            # Pre-compute VWAP bands for the full day once (O(n), not O(n²))
            try:
                _vb = compute_vwap_bands(day_df, num_stds=(1, 2))
                day_df = day_df.copy()
                day_df["vwap"]        = _vb["vwap"].ffill()
                day_df["vwap_upper1"] = _vb["vwap_upper1"].ffill()
                day_df["vwap_lower1"] = _vb["vwap_lower1"].ffill()
                day_df["vwap_upper2"] = _vb["vwap_upper2"].ffill()
                day_df["vwap_lower2"] = _vb["vwap_lower2"].ffill()
                day_df["vol_sma20"]   = day_df["volume"].rolling(100, min_periods=5).mean()
            except Exception:
                pass

            pnl = self._simulate_day(day_df, balance, day_str, _EVALUATORS_CACHED)
            balance += pnl
            if pnl != 0:
                daily_pnl[day_str] = pnl

        return self._compute_results(daily_pnl, balance)

    # ── Day simulation ────────────────────────────────────────────────────────

    def _simulate_day(
        self,
        day_df: pd.DataFrame,
        balance: float,
        day_str: str,
        evaluators: list,
    ) -> float:
        """
        Simulate a single trading day using all 8 strategy evaluators with the
        same quality gates and exit logic as the live trading bot.
        """
        from strategies.base import _signal_cooldown
        _signal_cooldown.clear()

        if len(day_df) < 5:
            return 0.0

        ticker_iv = _get_iv(self.ticker)

        in_trade              = False
        entry_price           = 0.0
        entry_strike          = 0.0
        entry_bar_time: Optional[pd.Timestamp] = None
        option_type           = "call"
        contracts             = 0       # integer contract count (live bot units)
        remaining_contracts   = 0       # contracts left after stage 1 sell
        stage1_done           = False
        session_pnl           = 0.0
        active_strategy       = "UNKNOWN"
        entry_date_str        = day_str

        for idx in range(4, len(day_df)):
            bar   = day_df.iloc[idx]
            close = float(bar["close"])
            ts    = bar["time"]

            # ── Manage open position ──────────────────────────────────────────
            if in_trade:
                elapsed_min = (ts - entry_bar_time).total_seconds() / 60

                # Reprice the same contract (fixed strike, 5 DTE)
                opt_price = _estimate_option_price(
                    close, entry_strike, 5, iv=ticker_iv, option_type=option_type,
                )

                # ── Exit 1: Early momentum stop ───────────────────────────────
                # If the trade is down > EARLY_STOP_PCT (12%) in first
                # EARLY_TIMEBOX_MIN (30 min), the setup failed — exit immediately.
                # Prevents deep theta burns on fast-moving false breakouts.
                if (not stage1_done
                        and elapsed_min <= EARLY_TIMEBOX_MIN
                        and opt_price <= entry_price * (1.0 - EARLY_STOP_PCT)):
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_contracts, option_type,
                        "early_momentum_stop", ts.hour, round(elapsed_min, 1),
                        active_strategy, entry_date_str,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                # ── Exit 2: Dynamic hard stop ─────────────────────────────────
                # Tightens 5pp every 15 min (theta decay protection):
                #   0–14 min  → 20% stop
                #   15–29 min → 15% stop
                #   ≥30 min   → floor 10%
                elapsed_steps  = int(elapsed_min / self.STOP_TIGHTEN_INTERVAL)
                dynamic_sl_pct = max(
                    self.ORB_STOP_PCT - elapsed_steps * self.STOP_TIGHTEN_STEP,
                    self.STOP_FLOOR_PCT,
                )
                sl_price = entry_price * (1.0 - dynamic_sl_pct)

                if opt_price <= sl_price:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_contracts, option_type,
                        "stop_loss", ts.hour, round(elapsed_min, 1),
                        active_strategy, entry_date_str,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                # ── Exit 3: Stage 1 — sell 50% at +50% ───────────────────────
                if not stage1_done:
                    s1_price = entry_price * (1.0 + self.ORB_STAGE1_GAIN)
                    if opt_price >= s1_price:
                        s1_exit_px    = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                        s1_contracts  = max(1, contracts // 2)
                        s1_pnl        = (s1_exit_px - entry_price) * s1_contracts * 100
                        session_pnl  += s1_pnl
                        self.trades.append({
                            "strategy_id":   active_strategy,
                            "option_type":   option_type,
                            "direction":     "long" if option_type == "call" else "short",
                            "entry_price":   entry_price,
                            "exit_price":    s1_exit_px,
                            "contracts":     s1_contracts,
                            "pnl":           round(s1_pnl, 2),
                            "exit_reason":   "stage1_50pct",
                            "entry_hour":    entry_bar_time.hour,
                            "held_minutes":  round(elapsed_min, 1),
                            "date":          entry_date_str,
                        })
                        remaining_contracts = contracts - s1_contracts
                        stage1_done         = True
                        continue

                # ── Exit 4: Stage 2 floor ─────────────────────────────────────
                # Live bot: exit remainder if price drops back to entry × 1.15
                # (not break-even). Locks in 15% profit floor on stage-2 leg.
                if stage1_done:
                    stage2_floor = entry_price * (1.0 + STAGE2_TRAIL_PCT)
                    if opt_price <= stage2_floor:
                        exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                        pnl = self._close_bt_trade(
                            entry_price, exit_px, remaining_contracts, option_type,
                            "stage2_trail_floor", ts.hour, round(elapsed_min, 1),
                            active_strategy, entry_date_str,
                        )
                        session_pnl += pnl
                        in_trade = False
                        continue

                # ── Exit 5a: Momentum-death early exit ───────────────────────
                # If RVOL has dropped below MOMENTUM_DEAD_RVOL AND the trade
                # is losing AND ≥ MOMENTUM_DEAD_MIN minutes have elapsed, exit
                # before the hard cap — institutional participation is gone.
                _bar_rvol = float(day_df.iloc[idx].get("rvol", 0.0)) if "rvol" in day_df.columns else 0.0
                if (not stage1_done
                        and _bar_rvol > 0.0
                        and _bar_rvol < MOMENTUM_DEAD_RVOL
                        and elapsed_min >= MOMENTUM_DEAD_MIN
                        and opt_price < entry_price):
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_contracts, option_type,
                        f"momentum_dead_exit (rvol={_bar_rvol:.2f})", ts.hour, round(elapsed_min, 1),
                        active_strategy, entry_date_str,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                # ── Exit 5b: Time-box — losers hard cap (60 min) ─────────────
                # Extended from 30 → 60 min; momentum-death check above kills
                # dead trades faster than the clock for most cases.
                if not stage1_done and elapsed_min >= EARLY_TIMEBOX_MIN:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_contracts, option_type,
                        f"time_box_{EARLY_TIMEBOX_MIN}m", ts.hour, round(elapsed_min, 1),
                        active_strategy, entry_date_str,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                # ── Exit 5b: Time-box — winners (stage1 IS done) ─────────────
                # Let winners breathe up to ORB_TIME_BOX_WINNER (90 min).
                if stage1_done and elapsed_min >= self.ORB_TIME_BOX_WINNER:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_contracts, option_type,
                        "time_box_90m", ts.hour, round(elapsed_min, 1),
                        active_strategy, entry_date_str,
                    )
                    session_pnl += pnl
                    in_trade = False
                    continue

                continue   # still holding

            # ── Signal detection ──────────────────────────────────────────────
            bar_slice = day_df.iloc[:idx + 1]

            raw_signals = []
            for strategy_id, fn in evaluators:
                try:
                    sig = fn(bar_slice, ticker=self.ticker)
                    if sig is not None:
                        raw_signals.append(sig)
                except Exception as _strat_ex:
                    logger.debug(
                        "BT strategy %s raised exception on bar %s: %s",
                        strategy_id, bar.get("time", idx), _strat_ex,
                    )

            if not raw_signals:
                continue

            # Track diagnostics
            self._diag["raw_signals"] += 1
            for _s in raw_signals:
                if _s.confidence > self._diag["max_confidence"]:
                    self._diag["max_confidence"] = round(_s.confidence, 4)
            # Sample a few RVOL values
            _bar_rvol = float(bar.get("rvol", 0) or 0)
            if len(self._diag["rvol_samples"]) < 20 and _bar_rvol > 0:
                self._diag["rvol_samples"].append(round(_bar_rvol, 2))

            raw_signals.sort(key=lambda s: s.confidence, reverse=True)

            # ── Session bias penalty (mirrors strategy_router logic) ───────────
            # Use session open only — VWAP excluded (redundant with strategy gates).
            if raw_signals and idx >= 1:
                _bt_first   = day_df.iloc[0]
                _bt_last    = bar_slice.iloc[-1]
                _bt_open    = float(_bt_first.get("open", _bt_first["close"]))
                _bt_close   = float(_bt_last["close"])
                _bt_bearish = _bt_close < _bt_open
                _bt_bullish = _bt_close > _bt_open
                if _bt_bearish or _bt_bullish:
                    for _sig in raw_signals:
                        _counter = (
                            (_bt_bearish and _sig.direction == "bullish") or
                            (_bt_bullish and _sig.direction == "bearish")
                        )
                        if _counter:
                            _sig.confidence = max(0.0, _sig.confidence - _SESSION_BIAS_PENALTY)
                    raw_signals.sort(key=lambda s: s.confidence, reverse=True)

            # ── Quality gate 1: confidence floor ─────────────────────────────
            signals = [s for s in raw_signals if s.confidence >= _MIN_CONFIDENCE]
            if not signals:
                self._diag["below_floor"] += 1
                continue

            # ── Quality gate 2: conflict veto ─────────────────────────────────
            if len(signals) >= 2:
                _top, _second = signals[0], signals[1]
                if (_top.direction != _second.direction and
                        (_top.confidence - _second.confidence) <= _CONFLICT_VETO_BAND):
                    self._diag["conflict_veto"] += 1
                    continue

            signal    = signals[0]
            direction = signal.direction
            strat_id  = signal.strategy_id

            # Direction filter
            opt_type_str = "call" if direction == "bullish" else "put"
            if self.direction == "calls_only" and opt_type_str != "call":
                self._diag["direction_skip"] += 1
                continue
            if self.direction == "puts_only"  and opt_type_str != "put":
                self._diag["direction_skip"] += 1
                continue

            # ── Simulate entry ────────────────────────────────────────────────
            strike      = _simulated_strike(close, direction)
            raw_opt_px  = _estimate_option_price(
                close, strike, 5, iv=ticker_iv, option_type=opt_type_str,
            )
            if raw_opt_px <= 0.0:
                continue

            # Apply entry slippage (pay 5% more than quoted ask)
            entry_opt_px = round(raw_opt_px * (1.0 + self.SLIPPAGE_PCT), 4)
            if entry_opt_px <= 0.0:
                continue

            # ── Contract sizing — same 4-tier risk ladder as live bot ─────────
            n_contracts = self._size_contracts(balance, entry_opt_px)
            if n_contracts <= 0:
                self._diag["no_contracts"] += 1
                continue   # can't afford even 1 contract

            in_trade            = True
            entry_price         = entry_opt_px
            entry_strike        = strike
            option_type         = opt_type_str
            entry_bar_time      = ts
            contracts           = n_contracts
            remaining_contracts = n_contracts
            stage1_done         = False
            active_strategy     = strat_id
            entry_date_str      = day_str

        # ── EOD: force-close any open position ───────────────────────────────
        if in_trade and remaining_contracts > 0:
            last_bar   = day_df.iloc[-1]
            last_close = float(last_bar["close"])
            eod_mid    = _estimate_option_price(
                last_close, entry_strike, 5, iv=ticker_iv, option_type=option_type,
            )
            eod_price = round(eod_mid * (1.0 - self.SLIPPAGE_PCT), 4)
            eod_time  = last_bar["time"]
            elapsed   = (eod_time - entry_bar_time).total_seconds() / 60 if entry_bar_time else 0
            pnl = self._close_bt_trade(
                entry_price, eod_price, remaining_contracts, option_type,
                "eod", eod_time.hour if not isinstance(eod_time, float) else 15,
                round(elapsed, 1), active_strategy, entry_date_str,
            )
            session_pnl += pnl

        return session_pnl

    # ── Trade recorder ────────────────────────────────────────────────────────

    def _close_bt_trade(
        self,
        entry_price: float,
        exit_price: float,
        n_contracts: int,
        option_type: str,
        reason: str,
        entry_hour: int = 10,
        held_minutes: float = 0.0,
        strategy_id: str = "UNKNOWN",
        date: str = "",
    ) -> float:
        """
        Record a simulated trade and return its P&L.

        P&L uses real contract math: (exit - entry) × contracts × 100
        This is what the live bot computes in database.close_trade().
        """
        if entry_price <= 0.0 or n_contracts <= 0:
            return 0.0
        pnl = (exit_price - entry_price) * n_contracts * 100
        self.trades.append({
            "strategy_id":   strategy_id,
            "option_type":   option_type,
            "direction":     "long" if option_type == "call" else "short",
            "entry_price":   entry_price,
            "exit_price":    exit_price,
            "contracts":     n_contracts,
            "pnl":           round(pnl, 2),
            "exit_reason":   reason,
            "entry_hour":    entry_hour,
            "held_minutes":  held_minutes,
            "date":          date,
        })
        return pnl

    # ── Results aggregation ───────────────────────────────────────────────────

    def _compute_results(self, daily_pnl: dict, final_balance: float) -> dict:
        """Aggregate backtest trades into summary statistics."""
        trades = self.trades
        pnls   = [t["pnl"] for t in trades]

        if not pnls:
            diag = getattr(self, "_diag", {})
            _rvol_str = str(diag.get("rvol_samples", [])[:10])
            return {
                "error": (
                    f"No trades generated. "
                    f"Bars={diag.get('total_bars',0)} "
                    f"Days={diag.get('trading_days',0)} "
                    f"RawSignalBars={diag.get('raw_signals',0)} "
                    f"BelowFloor={diag.get('below_floor',0)} "
                    f"ConflictVeto={diag.get('conflict_veto',0)} "
                    f"DirSkip={diag.get('direction_skip',0)} "
                    f"NoContracts={diag.get('no_contracts',0)} "
                    f"MaxConf={diag.get('max_confidence',0.0):.4f} "
                    f"RVOLsamples={_rvol_str}"
                )
            }

        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Per-strategy breakdown
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

        # Call vs Put breakdown
        calls     = [t for t in trades if t.get("option_type") == "call"]
        puts      = [t for t in trades if t.get("option_type") == "put"]
        call_wins = [t for t in calls if t["pnl"] > 0]
        put_wins  = [t for t in puts  if t["pnl"] > 0]

        # Exit reason breakdown
        exit_reasons: dict = {}
        for t in trades:
            r = t.get("exit_reason", "unknown")
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "pnl": 0.0}
            exit_reasons[r]["count"] += 1
            exit_reasons[r]["pnl"]   += t["pnl"]

        # Hold time
        held_times = [t.get("held_minutes", 0) for t in trades if t.get("held_minutes", 0) > 0]
        avg_hold   = round(sum(held_times) / len(held_times), 1) if held_times else 0.0

        # Stage-1 hit rate
        stage1_exits = [t for t in trades if t.get("exit_reason") == "stage1_50pct"]
        stage1_rate  = len(stage1_exits) / max(len(trades), 1) * 100

        # Avg contracts per trade
        avg_contracts = round(
            sum(t.get("contracts", 1) for t in trades) / max(len(trades), 1), 1
        )

        # Max consecutive losses
        max_consec, cur_consec = 0, 0
        for p in pnls:
            if p <= 0:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec = 0

        # Core stats
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
            "risk_pct_used":    self.risk_pct_override,   # None = tier ladder
            "avg_contracts":    avg_contracts,
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
            # Per-strategy breakdown
            "strategy_breakdown": strategy_breakdown,
            # Time / exit analysis
            "exit_reasons":     exit_reasons,
            "daily_pnl":        daily_pnl,
            "trades":           trades,
        }
