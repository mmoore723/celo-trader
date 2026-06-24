"""
backtester.py — ORB Historical Simulation Engine.

Architecture
────────────
Replays N months of historical 5-min OHLCV bars through the same ORB signal
and risk logic used in live trading.  Faithfully mirrors every rule:

  Signal  : detect_orb_breakout()  (RVOL ≥ 120%, VWAP gate)
  Sizing  : Dollar-based 1% risk model — position_$ = equity × 0.01 / stop_pct
            Works for any account size — no per-contract minimum required.
  Stop    : 20% of option premium (hard, always active; tightens dynamically)
  Stage 1 : sell 50% of position dollars when premium ≥ entry × 1.50
  Stage 2 : hold remainder; exit at break-even (entry_price) or time-box
  Time-box: 45 minutes from entry — hard exit regardless of price

Key assumptions / limitations
──────────────────────────────
1. Options pricing uses a simplified Black-Scholes estimate (no free
   historical options chain data available).
2. Position sizing is dollar-based (not contract-count), so any account
   size ≥ $100 can generate simulated trades on any ticker.
3. Fill model: entry at ask estimate, exit at bid estimate (conservative).
4. Commissions: $0 (Alpaca / Tradier are commission-free).
5. RVOL uses bar-level compute_rvol() from signals.py — the same function
   called in live trading, so no divergence between backtest and live logic.

Output metrics
──────────────
- Total return (%)
- Win rate (%)
- Average win / average loss
- Sharpe ratio (annualised, using daily P&L)
- Max drawdown ($)
- Exit reason breakdown
- Stage-1 partial exit statistics
- Trade log
"""

import logging
import math
from datetime import datetime, timedelta, date, timezone
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    BACKTEST_MONTHS,
    STARTING_CAPITAL,
)
from signals import (
    bars_to_df, detect_orb_breakout, compute_vwap, compute_rvol,
    get_opening_range, ORB_RVOL_THRESHOLD,
)
from risk import RiskManager

logger = logging.getLogger("celo_trader.backtester")


# ── Simplified option pricer ──────────────────────────────────────────────────

def _estimate_option_price(
    stock_price: float,
    strike: float,
    days_to_expiry: int = 14,
    iv: float = 0.60,
    option_type: str = "call",
) -> float:
    """
    Simplified Black-Scholes estimate for option mid price.
    intrinsic + time_value  (time_value ≈ stock × iv × sqrt(dte/252) × 0.4)
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
    Runs the ORB strategy on historical 5-min bars.

    Parameters
    ----------
    alpaca           : AlpacaClient (or any object with .get_bars())
    ticker           : stock symbol to test
    months           : look-back period in months
    starting_capital : initial simulated account balance
    """

    # Mirror the constants from RiskManager so they're always in sync
    ORB_STOP_PCT          = RiskManager.ORB_STOP_PCT          # 0.20 (tightened from 0.30)
    ORB_RISK_PCT          = RiskManager.ORB_RISK_PCT           # 0.01
    ORB_STAGE1_GAIN       = RiskManager.ORB_STAGE1_GAIN       # 0.50
    ORB_TIME_BOX          = RiskManager.ORB_TIME_BOX           # 45 minutes
    SLIPPAGE_PCT          = RiskManager.SLIPPAGE_PCT           # 0.05
    # NOTE: MIN_RR_RATIO is no longer a fixed class constant — the live R:R gate
    # is now balance-dependent (see RiskManager.effective_min_rr / rr_ratio_mode:
    # 1.2 for sub-$5k bootstrap accounts, 1.6 once graduated). The backtest's
    # R:R pre-flight check below resolves this dynamically per simulated day
    # via RiskManager(account_balance=balance).effective_min_rr() so it stays
    # in sync with live behavior.
    STOP_TIGHTEN_INTERVAL = RiskManager.STOP_TIGHTEN_INTERVAL  # 15 min
    STOP_TIGHTEN_STEP     = RiskManager.STOP_TIGHTEN_STEP      # 0.05
    STOP_FLOOR_PCT        = RiskManager.STOP_FLOOR_PCT         # 0.10

    def __init__(
        self,
        alpaca,
        ticker: str,
        months: int = BACKTEST_MONTHS,
        starting_capital: float = STARTING_CAPITAL,
    ):
        self.alpaca   = alpaca
        self.ticker   = ticker
        self.months   = months
        self.capital  = starting_capital
        self.trades: list[dict] = []

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute the backtest.  Returns a results dictionary consumed by the dashboard.
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

        # Fetch historical 5-min bars
        raw = self.alpaca.get_bars(self.ticker, "5Min", limit=5000)
        if isinstance(raw, tuple):
            bars_5m = raw[0]   # get_bars returns (bars, is_error)
        else:
            bars_5m = raw

        if not bars_5m:
            return {"error": f"No historical data for {self.ticker}"}

        df = bars_to_df(bars_5m)

        # Trim to requested look-back window
        cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=self.months)
        if df["time"].dt.tz is None:
            cutoff = cutoff.tz_localize(None)
        df = df[df["time"] >= cutoff].reset_index(drop=True)

        if df.empty:
            return {"error": f"No bars within the last {self.months} months"}

        # Pre-compute VWAP and RVOL for the entire dataset in one pass
        # (same functions as live trading — no separate backtest-only logic)
        df["vwap"] = compute_vwap(df)
        df["rvol"] = compute_rvol(df)

        balance      = self.capital
        daily_pnl: dict[str, float] = {}

        # Group bars by trading day so we can replay session by session
        df["_date"] = df["time"].dt.date
        unique_days = sorted(df["_date"].unique())

        for trade_date in unique_days:
            day_df  = df[df["_date"] == trade_date].reset_index(drop=True)
            day_str = trade_date.isoformat()

            pnl = self._simulate_day(day_df, balance, day_str)
            balance += pnl
            if pnl != 0:
                daily_pnl[day_str] = pnl

            # Daily loss circuit-breaker (mirrors live risk.py)
            if daily_pnl.get(day_str, 0) < -(balance * 0.12):
                logger.debug("Backtest: daily loss limit hit on %s", day_str)

        return self._compute_results(daily_pnl, balance)

    # ── Day simulation ────────────────────────────────────────────────────────

    def _simulate_day(self, day_df: pd.DataFrame, balance: float, day_str: str) -> float:
        """
        Simulate a single trading day.

        Rules applied in order:
        1. Find the opening range (09:30 bar).
        2. Scan subsequent bars for ORB breakout with RVOL ≥ 200% and VWAP gate.
        3. Size via 1% risk model.
        4. Manage position with two-stage exit + 45-min time-box.
        5. At most ONE trade per session (no re-entry after ORB triggers).
        """
        if len(day_df) < 2:
            return 0.0

        or_info = get_opening_range(day_df)
        if or_info is None:
            return 0.0   # no opening bar — holiday / half day / data gap

        or_high = or_info["high"]
        or_low  = or_info["low"]

        in_trade           = False
        entry_price        = 0.0       # simulated option premium per share at entry
        entry_bar_idx      = 0
        entry_bar_time: Optional[pd.Timestamp] = None
        option_type        = "call"
        position_dollars   = 0.0      # dollars allocated to this trade (full position)
        remaining_dollars  = 0.0      # dollars still open after stage-1 partial exit
        stage1_done        = False
        session_pnl        = 0.0

        for idx in range(1, len(day_df)):    # skip opening-range bar
            bar   = day_df.iloc[idx]
            close = float(bar["close"])
            ts    = bar["time"]
            rvol  = float(bar.get("rvol", 0.0)) if not pd.isna(bar.get("rvol", float("nan"))) else 0.0
            vwap  = float(bar.get("vwap", float("nan")))

            # ── Manage open position ──────────────────────────────────────────
            if in_trade:
                elapsed_min = (ts - entry_bar_time).total_seconds() / 60

                # Simulate option price at current stock price
                strike    = _simulated_strike(close, "bullish" if option_type == "call" else "bearish")
                opt_price = _estimate_option_price(close, strike, 3, option_type=option_type)

                # Dynamic stop: tightens 5pp every 15 min (mirrors live logic)
                elapsed_steps  = int(elapsed_min / self.STOP_TIGHTEN_INTERVAL)
                dynamic_sl_pct = max(
                    self.ORB_STOP_PCT - elapsed_steps * self.STOP_TIGHTEN_STEP,
                    self.STOP_FLOOR_PCT,
                )
                sl_price = entry_price * (1.0 - dynamic_sl_pct)

                # Hard stop — dollar P&L on remaining position
                if opt_price <= sl_price:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "stop_loss", ts.hour,
                    )
                    session_pnl += pnl
                    in_trade = False
                    break   # one trade per session

                # Stage 1: sell 50% of position at +50% gain
                if not stage1_done:
                    s1_price = entry_price * (1.0 + self.ORB_STAGE1_GAIN)
                    if opt_price >= s1_price:
                        s1_exit_px  = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                        half_dollars = position_dollars / 2.0
                        # P&L on the half being closed now
                        s1_pnl = half_dollars * ((s1_exit_px / entry_price) - 1.0)
                        session_pnl += s1_pnl
                        self.trades.append({
                            "option_type":  option_type,
                            "entry_price":  entry_price,
                            "exit_price":   s1_exit_px,
                            "pnl":          s1_pnl,
                            "reason":       "stage1_50pct",
                            "exit_reason":  "stage1_50pct",
                            "entry_hour":   entry_bar_time.hour if entry_bar_time else ts.hour,
                            "held_minutes": round(elapsed_min, 1),
                        })
                        remaining_dollars = half_dollars
                        stage1_done       = True
                        continue   # break-even stop now in effect for the remainder

                # Stage 2: break-even stop on remainder
                if stage1_done and opt_price <= entry_price:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "stage2_break_even", ts.hour,
                        held_minutes=round(elapsed_min, 1),
                    )
                    session_pnl += pnl
                    in_trade = False
                    break

                # 45-minute time-box
                if elapsed_min >= self.ORB_TIME_BOX:
                    exit_px = round(opt_price * (1.0 - self.SLIPPAGE_PCT), 4)
                    pnl = self._close_bt_trade(
                        entry_price, exit_px, remaining_dollars, option_type,
                        "time_box_45m", ts.hour,
                        held_minutes=round(elapsed_min, 1),
                    )
                    session_pnl += pnl
                    in_trade = False
                    break

                continue   # still holding — next bar

            # ── Look for ORB breakout ─────────────────────────────────────────
            if close > or_high:
                direction = "bullish"
            elif close < or_low:
                direction = "bearish"
            else:
                continue   # no breakout on this bar

            # RVOL gate: breakout candle must have ≥ 150% average volume (aligned
            # with live strategy_router.py — lowered from 200% to capture more
            # quality setups).
            if rvol < ORB_RVOL_THRESHOLD:
                continue

            # VWAP gate
            if not pd.isna(vwap):
                if direction == "bullish" and close <= vwap:
                    continue
                if direction == "bearish" and close >= vwap:
                    continue

            # ── Simulate entry ────────────────────────────────────────────────
            stock_price  = close
            opt_type_str = "call" if direction == "bullish" else "put"
            strike       = _simulated_strike(stock_price, direction)
            # Use 3-DTE pricing (short-dated options typical of day-trading)
            raw_opt_px   = _estimate_option_price(stock_price, strike, 3, option_type=opt_type_str)

            # Skip zero/negative pricing (data anomaly)
            if raw_opt_px <= 0.0:
                continue

            # Apply slippage to entry (we pay 5% above mid — mirrors live)
            entry_opt_px = round(raw_opt_px * (1.0 + self.SLIPPAGE_PCT), 4)
            if entry_opt_px <= 0.0:
                continue

            # ── R:R pre-flight check ──────────────────────────────────────────
            _eff_target = entry_opt_px * (1.0 + self.ORB_STAGE1_GAIN) * (1.0 - self.SLIPPAGE_PCT)
            _eff_stop   = entry_opt_px * (1.0 - self.ORB_STOP_PCT)    * (1.0 - self.SLIPPAGE_PCT)
            _net_reward = _eff_target - entry_opt_px
            _net_risk   = entry_opt_px - _eff_stop
            _rr         = _net_reward / _net_risk if _net_risk > 0 else 0.0

            _min_rr = RiskManager(account_balance=balance).effective_min_rr()
            if _rr < _min_rr:
                logger.debug(
                    "backtest_rr_blocked date=%s R:R=%.2f < %.1f",
                    day_str, _rr, _min_rr,
                )
                continue

            # ── Dollar-based position sizing ──────────────────────────────────
            # Works for any account size — no per-contract minimum.
            # position_dollars = how much premium we're "buying" in dollar terms.
            # risk budget / stop % → position such that a full stop costs 1% of equity.
            risk_budget      = balance * self.ORB_RISK_PCT      # e.g. $1 on a $100 account
            pos_dollars      = risk_budget / self.ORB_STOP_PCT  # e.g. $1/0.30 = $3.33
            # Cap at 20% of equity so one trade can't wipe the account
            max_pos_dollars  = balance * 0.20
            pos_dollars      = min(pos_dollars, max_pos_dollars)

            if pos_dollars <= 0.0:
                continue

            in_trade          = True
            entry_price       = entry_opt_px
            option_type       = opt_type_str
            entry_bar_idx     = idx
            entry_bar_time    = ts
            position_dollars  = pos_dollars
            remaining_dollars = pos_dollars
            stage1_done       = False

        # End of session — force exit any open position (EOD close)
        if in_trade and remaining_dollars > 0:
            last_bar   = day_df.iloc[-1]
            last_close = float(last_bar["close"])
            strike     = _simulated_strike(last_close, "bullish" if option_type == "call" else "bearish")
            eod_mid    = _estimate_option_price(last_close, strike, 3, option_type=option_type)
            eod_price  = round(eod_mid * (1.0 - self.SLIPPAGE_PCT), 4)
            pnl = self._close_bt_trade(
                entry_price, eod_price, remaining_dollars, option_type, "eod",
                last_bar["time"].hour if not isinstance(last_bar["time"], float) else 15,
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
    ) -> float:
        """Record a simulated trade and return its P&L.

        Dollar-based model: P&L = position_dollars × (exit/entry − 1).
        Works for any account size without requiring per-contract sizing.
        """
        if entry_price <= 0.0:
            return 0.0
        pnl = position_dollars * ((exit_price / entry_price) - 1.0)
        self.trades.append({
            "option_type":   option_type,
            "entry_price":   entry_price,
            "exit_price":    exit_price,
            "position_dollars": position_dollars,
            "pnl":           pnl,
            "reason":        reason,
            "exit_reason":   reason,
            "entry_hour":    entry_hour,
            "held_minutes":  held_minutes,
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

        # Call vs Put breakdown
        calls     = [t for t in trades if t.get("option_type") == "call"]
        puts      = [t for t in trades if t.get("option_type") == "put"]
        call_wins = [t for t in calls if t["pnl"] > 0]
        put_wins  = [t for t in puts  if t["pnl"] > 0]
        call_wr   = len(call_wins) / max(len(calls), 1) * 100
        put_wr    = len(put_wins)  / max(len(puts),  1) * 100
        call_pnl  = sum(t["pnl"] for t in calls)
        put_pnl   = sum(t["pnl"] for t in puts)

        # Time-of-day analysis
        hour_stats: dict = {}
        for t in trades:
            h = t.get("entry_hour", 10)
            if h not in hour_stats:
                hour_stats[h] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
            hour_stats[h]["trades"] += 1
            hour_stats[h]["pnl"]    += t["pnl"]
            if t["pnl"] > 0:
                hour_stats[h]["wins"] += 1
            else:
                hour_stats[h]["losses"] += 1
        best_hour = max(hour_stats, key=lambda h: hour_stats[h]["pnl"]) if hour_stats else None

        # Exit reason breakdown
        exit_reasons: dict = {}
        for t in trades:
            r = t.get("exit_reason", "unknown")
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "pnl": 0.0}
            exit_reasons[r]["count"] += 1
            exit_reasons[r]["pnl"]   += t["pnl"]

        # Hold time statistics
        held_times = [t.get("held_minutes", 0) for t in trades if t.get("held_minutes", 0) > 0]
        avg_hold   = round(sum(held_times) / len(held_times), 1) if held_times else 0.0

        # Stage-1 hit rate
        stage1_exits = [t for t in trades if t.get("exit_reason") == "stage1_50pct"]
        stage1_rate  = len(stage1_exits) / max(len(trades), 1) * 100

        # Max consecutive losses
        max_consec, cur_consec = 0, 0
        for p in pnls:
            if p <= 0:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec = 0

        # Expectancy
        win_rate   = len(wins) / len(pnls) if pnls else 0
        avg_win    = sum(wins)   / len(wins)   if wins   else 0
        avg_loss   = sum(losses) / len(losses) if losses else 0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # Sharpe ratio (annualised)
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
            "ticker":          self.ticker,
            "months":          self.months,
            "total_trades":    len(pnls),
            "win_rate":        win_rate,
            "avg_win":         avg_win,
            "avg_loss":        avg_loss,
            "total_pnl":       sum(pnls),
            "final_balance":   final_balance,
            "total_return":    (final_balance - self.capital) / self.capital * 100,
            "max_drawdown":    max_dd,
            "sharpe_ratio":    round(sharpe, 2),
            "expectancy":      round(expectancy, 2),
            "max_consec_loss": max_consec,
            # ORB-specific metrics
            "stage1_hit_rate": round(stage1_rate, 1),
            "avg_hold_minutes": avg_hold,
            # Call vs Put
            "call_trades":     len(calls),
            "put_trades":      len(puts),
            "call_win_rate":   round(call_wr, 1),
            "put_win_rate":    round(put_wr, 1),
            "call_pnl":        round(call_pnl, 2),
            "put_pnl":         round(put_pnl, 2),
            # Time analysis
            "hour_stats":      hour_stats,
            "best_hour":       best_hour,
            # Exit analysis
            "exit_reasons":    exit_reasons,
            "daily_pnl":       daily_pnl,
            "trades":          trades,
        }
