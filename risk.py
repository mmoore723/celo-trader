"""
risk.py — Risk management layer with Dynamic Sizing Ladder and Thread-Safe Locks.

Growth Mode additions:
  - get_risk_tier(balance)          : returns 3% (<$50k) or 1% (>=$50k)
  - DAILY_LOSS_HARD_CAP_PCT = 0.10  : hard 10% daily cap, always enforced
  - kill lock                       : 24-hour trading freeze written to kill_lock.json
"""

import json
import logging
import threading
import time as _time
from datetime import datetime, time as dtime, date, timedelta
from pathlib import Path
from typing import Optional

# HIGH RISK WARNING fires at most ONCE PER SESSION (per service start).
# Previously capped at 5 minutes — still noisy for a user who checks the
# dashboard periodically. Session-scoped flag is reset when the service restarts.
_bootstrap_warn_shown: bool = False

from config import (
    get_settings, get_risk_tier,
    STARTING_CAPITAL, DAILY_LOSS_HARD_CAP_PCT, KILL_LOCK_HOURS,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT, MID_TIER_RISK_PCT, CONSERVATIVE_RISK_PCT,
    GROWTH_RISK_BOUNDARY_BOOT, MIN_RR_RATIO_SMALL_ACCOUNT, MIN_RR_RATIO_PROFESSIONAL,
    EARLY_TIMEBOX_MIN, EARLY_STOP_PCT, STAGE2_TRAIL_PCT,
    MOMENTUM_DEAD_RVOL, MOMENTUM_DEAD_MIN,
)
from database import log_event, get_conn

logger   = logging.getLogger("celo_trader.risk")
db_mutex = threading.Lock()  # Thread lock prevents SQLite concurrent write crashes

# ── Kill lock helpers ─────────────────────────────────────────────────────────
_KILL_LOCK_PATH = Path(__file__).resolve().parent / "kill_lock.json"


def set_kill_lock(hours: Optional[int] = None) -> datetime:
    """
    Write a kill-lock file that blocks all trading for `hours` hours.
    Returns the datetime when the lock expires.
    """
    lock_hours = hours or int(get_settings().get("kill_lock_hours", KILL_LOCK_HOURS))
    expires_at = datetime.utcnow() + timedelta(hours=lock_hours)
    try:
        _KILL_LOCK_PATH.write_text(json.dumps({
            "locked_until_utc": expires_at.isoformat(),
            "set_at_utc":       datetime.utcnow().isoformat(),
            "reason":           "daily_loss_hard_cap",
        }))
        logger.warning(
            "kill_lock_set",
            extra={
                "event":       "kill_lock_set",
                "expires_utc": expires_at.isoformat(),
                "lock_hours":  lock_hours,
            },
        )
    except Exception as ex:
        logger.error("Failed to write kill lock: %s", ex)
    return expires_at


def check_kill_lock() -> tuple[bool, Optional[str]]:
    """
    Returns (locked: bool, reason: str | None).
    Locked = True means trading must be blocked until the timestamp expires.
    """
    if not _KILL_LOCK_PATH.exists():
        return False, None
    try:
        data       = json.loads(_KILL_LOCK_PATH.read_text())
        expires_at = datetime.fromisoformat(data["locked_until_utc"])
        if datetime.utcnow() < expires_at:
            remaining = expires_at - datetime.utcnow()
            hours_left = remaining.total_seconds() / 3600
            return True, f"Kill-locked: {hours_left:.1f}h remaining (expires {expires_at.strftime('%Y-%m-%d %H:%M')} UTC)"
        else:
            # Lock expired — clean up
            _KILL_LOCK_PATH.unlink(missing_ok=True)
    except Exception as ex:
        logger.warning("kill lock read error: %s", ex)
    return False, None


def clear_kill_lock() -> None:
    """Manually clear the kill lock (for admin / dashboard use)."""
    try:
        _KILL_LOCK_PATH.unlink(missing_ok=True)
        logger.info("kill_lock_cleared", extra={"event": "kill_lock_cleared"})
    except Exception:
        pass


class DailyLossLimitReached(Exception):
    pass


# ── Structural stop helpers ───────────────────────────────────────────────────

def find_structural_stop(
    df,                     # pd.DataFrame with OHLCV + "time" column
    direction: str,         # "bullish" (CALL) or "bearish" (PUT)
    lookback: int = 30,     # recent bars to scan for pivots
    pivot_bars: int = 3,    # bars on each side for pivot confirmation
) -> Optional[float]:
    """
    Return the most recent structural swing price that defines the stop-loss.

    For a CALL (bullish):  stop = most recent Swing Low
      — last structural support; if it breaks, the bullish thesis is invalidated.

    For a PUT (bearish):   stop = most recent Swing High
      — last structural resistance; if price reclaims it, the bearish thesis is wrong.

    Uses an N-bar pivot: a bar whose high (or low) exceeds all bars within
    `pivot_bars` bars on each side.  Returns None when insufficient data exists;
    callers should fall back to ORB_STOP_PCT in that case.
    """
    try:
        if df is None or len(df) < 2 * pivot_bars + 1:
            return None

        window = df.iloc[-min(lookback, len(df)):].reset_index(drop=True)
        n      = len(window)

        pivots = []
        for i in range(pivot_bars, n - pivot_bars):
            bar   = window.iloc[i]
            left  = window.iloc[i - pivot_bars : i]
            right = window.iloc[i + 1 : i + pivot_bars + 1]

            if direction == "bullish":
                # Swing Low — stop for CALL entries
                if (float(bar["low"]) < float(left["low"].min()) and
                        float(bar["low"]) < float(right["low"].min())):
                    pivots.append(float(bar["low"]))
            else:
                # Swing High — stop for PUT entries
                if (float(bar["high"]) > float(left["high"].max()) and
                        float(bar["high"]) > float(right["high"].max())):
                    pivots.append(float(bar["high"]))

        return pivots[-1] if pivots else None

    except Exception as ex:
        logger.debug("find_structural_stop error (%s): %s", direction, ex)
        return None


# ── Database helpers for persistent state ─────────────────────────────────────

def get_todays_realized_pnl() -> float:
    """
    Read today's realized P&L directly from the database with an operational thread lock.
    """
    today = date.today().isoformat()
    try:
        with db_mutex:
            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(realized_pnl), 0.0)
                    FROM trades
                    WHERE status = 'closed'
                      AND date(exit_time) = ?
                      AND paper = 0
                    """,
                    (today,),
                ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error("get_todays_realized_pnl failed: %s", e)
        return 0.0


def persist_peak_price(trade_id: int, peak_price: float) -> None:
    """
    Write peak price to the system_events table so it survives unexpected restarts.
    """
    try:
        with db_mutex:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO system_events (ts, level, component, message)
                    VALUES (?, 'INFO', 'peak_price', ?)
                    """,
                    (datetime.utcnow().isoformat(), f"trade_id={trade_id} peak={peak_price:.4f}"),
                )
    except Exception as e:
        logger.warning("persist_peak_price failed (non-critical): %s", e)


def recover_peak_price(trade_id: int) -> Optional[float]:
    """
    Recover peak price from DB after a workspace crash or engine restart.
    """
    try:
        with db_mutex:
            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT message FROM system_events
                    WHERE component = 'peak_price'
                      AND message LIKE ?
                    ORDER BY ts DESC LIMIT 1
                    """,
                    (f"trade_id={trade_id}%",),
                ).fetchone()
        if row:
            parts = dict(kv.split("=") for kv in row[0].split())
            return float(parts.get("peak", 0))
    except Exception:
        pass
    return None


# ── Risk Manager ──────────────────────────────────────────────────────────────

class RiskManager:

    def __init__(self, account_balance: float = STARTING_CAPITAL):
        self.account_balance = account_balance
        self.daily_limit_hit = False
        self._last_check_date = date.today()

    def maybe_reset_for_new_day(self) -> None:
        today = date.today()
        if today != self._last_check_date:
            self.daily_limit_hit = False
            self._last_check_date = today
            logger.info("New trading day — daily limit flag reset")

    def is_trading_window(self, now: Optional[datetime] = None) -> bool:
        # Use balance-aware get_trading_windows() so the Phase 2 extended window
        # (09:45–11:30) automatically activates once the account clears $25k.
        from config import get_trading_windows as _gtw
        windows = _gtw(self.account_balance)
        t = (now or datetime.now()).time()
        for start_str, end_str in windows:
            s = dtime(*map(int, start_str.split(":")))
            e = dtime(*map(int, end_str.split(":")))
            if s <= t <= e:
                return True
        return False

    def get_dynamic_position_limits(self, current_balance: float) -> tuple[float, float]:
        """Calculates dynamic percentage sizing and dollar caps based on account milestones."""
        settings = get_settings()
        p2_boundary = settings.get("phase_2_boundary", 25000.0)
        p3_boundary = settings.get("phase_3_boundary", 100000.0)

        if current_balance < p2_boundary:
            pct = settings.get("phase_1_aggressive_pct", 0.15)
            max_dollars = p2_boundary * pct 
        elif current_balance < p3_boundary:
            pct = settings.get("phase_2_moderate_pct", 0.08)
            max_dollars = p3_boundary * pct
        else:
            pct = settings.get("phase_3_conservative_pct", 0.03)
            max_dollars = max(current_balance * pct, settings.get("phase_3_hard_cap_usd", 5000.0))

        return pct, max_dollars

    # ── ORB Risk Model (tiered) ───────────────────────────────────────────────
    # Position size = (Equity × RISK_PCT) / (Premium × 0.30)
    #
    # Growth mode ON  + balance < $50k  → RISK_PCT = 3%
    # Growth mode ON  + balance >= $50k → RISK_PCT = 1% (auto-downgrade)
    # Growth mode OFF                   → RISK_PCT = 1%
    #
    # The result is always floored to 1 (we enter if we can afford ≥ 1 contract)
    # or 0 if even 1 contract would risk more than the RISK_PCT budget.

    ORB_STOP_PCT        = 0.20   # initial stop-loss = 20% of premium (tightened from 30%
                                 # — smaller hole to dig out of on a <$5k account)
    ORB_RISK_PCT        = 0.01   # baseline risk % — used for R:R display / logging
    ORB_STAGE1_PCT      = 0.50   # sell 50% of contracts at +50% profit
    ORB_STAGE1_GAIN     = 0.50   # +50% gain threshold for stage-1 exit
    ORB_TIME_BOX        = 45     # flat/losing hard cap (stage1 NOT done)
    ORB_TIME_BOX_WINNER = 90     # extended cap when stage1 IS done (let winners run)

    # ── 1.5× Profit-Factor enforcement ───────────────────────────────────────
    MIN_RR_RATIO        = 1.6    # minimum reward-to-risk before entry is allowed
    SLIPPAGE_PCT        = 0.05   # 5% slippage buffer applied to entry & profit target

    # ── Dynamic stop tightening (theta decay protection) ─────────────────────
    # Stop tightens 5 percentage-points every 15 minutes:
    #   0–14 min  → 20% stop (initial — tightened from 30%)
    #   15–29 min → 15% stop
    #   ≥30 min   → floor (10%) — never goes below STOP_FLOOR_PCT
    #   ≥45 min   → time-box exits flat/losing trades entirely
    #   ≥90 min   → time-box exits winners (stage1_done=True)
    STOP_TIGHTEN_INTERVAL = 15   # minutes between each tightening step
    STOP_TIGHTEN_STEP     = 0.05 # 5pp reduction per step
    STOP_FLOOR_PCT        = 0.10 # never tighten below 10% (avoid noise-triggered exits)

    # ── Volatility-adjusted profit lock ──────────────────────────────────────
    # Once the trade has been up PROFIT_LOCK_PCT (12%), protect the gain:
    #   Primary:  ATR-based trail (position_manager keeps it current)
    #   Fallback: hard floor at entry + PROFIT_LOCK_TRAIL_PCT (3%)
    # Rationale: waiting for +50% (old Stage-1) means most winning setups
    # that move 12–30% and reverse give back ALL profit. The lock captures
    # consistent smaller wins that compound favourably on a small account.
    PROFIT_LOCK_PCT       = 0.12   # +12% gain triggers profit protection
    PROFIT_LOCK_TRAIL_PCT = 0.03   # minimum profit to lock in (entry + 3%)

    def effective_risk_pct(self, balance: Optional[float] = None) -> float:
        """
        Return the active risk % for the given balance.

        Reads config.get_risk_tier() fresh on every call so that changes saved
        via the dashboard Risk Settings page take effect on the very next trade
        without a bot restart.

        If the resolved risk is 5% (BOOTSTRAP_RISK_PCT), a WARNING is printed
        to both the Python logger and stdout so it appears clearly in every
        log destination (file, console, Streamlit log viewer).
        """
        bal      = balance or self.account_balance
        risk_pct = get_risk_tier(bal)   # reads user_settings.json on every call

        if risk_pct >= BOOTSTRAP_RISK_PCT:
            # Fire at most ONCE per session (per service start). Previously
            # capped at 5 min which still flooded the Thinking panel hourly.
            global _bootstrap_warn_shown
            if not _bootstrap_warn_shown:
                _bootstrap_warn_shown = True
                _warn_msg = (
                    "WARNING: HIGH RISK MODE ENABLED: 5% RISK PER TRADE — "
                    f"balance=${bal:,.2f} risk_budget=${bal * risk_pct:,.2f}"
                )
                logger.warning(_warn_msg)
                print(_warn_msg)   # also echoed to stdout / Streamlit console

        return risk_pct

    def effective_min_rr(self, balance: Optional[float] = None) -> float:
        """
        Return the active minimum R:R (reward:risk) gate threshold for the
        given balance.

        Reads 'rr_ratio_mode' from user_settings.json fresh on every call so
        changes saved via the dashboard Risk Settings page take effect on the
        very next R:R evaluation without a bot restart.

        Modes (settings["rr_ratio_mode"]):
          "auto" (default) — balance-based switch. While balance is below the
            bootstrap boundary (growth_risk_boundary_boot, default $5,000) the
            relaxed MIN_RR_RATIO_SMALL_ACCOUNT (1.2) gate applies. Once the
            balance reaches/crosses that boundary, the bot automatically
            switches to MIN_RR_RATIO_PROFESSIONAL (1.6).
          "small_account"  — always MIN_RR_RATIO_SMALL_ACCOUNT (1.2).
          "professional"   — always MIN_RR_RATIO_PROFESSIONAL (1.6).
        """
        bal      = balance or self.account_balance
        settings = get_settings()
        mode     = settings.get("rr_ratio_mode", "auto")

        if mode == "small_account":
            return MIN_RR_RATIO_SMALL_ACCOUNT
        if mode == "professional":
            return MIN_RR_RATIO_PROFESSIONAL

        # "auto" (default): balance-based switch at the bootstrap tier boundary
        boundary_boot = float(settings.get("growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT))
        if bal < boundary_boot:
            return MIN_RR_RATIO_SMALL_ACCOUNT   # 1.2 — small/bootstrap account
        return MIN_RR_RATIO_PROFESSIONAL        # 1.6 — graduated to professional standard

    def calculate_contracts(self, option_ask: float, account_balance: Optional[float] = None) -> int:
        """
        ORB tiered risk model.

        Formula: floor( (equity × RISK_PCT) / (premium × 0.30 × 100) )

        RISK_PCT is 3% when growth_mode is ON and balance < $50k, else 1%.
        A single contract risks: premium × 0.30 × 100 dollars.
        Minimum 1 contract if the premium fits within the notional cap (30% growth / 20% conservative).
        Returns 0 only when the single-contract premium exceeds the notional cap.
        """
        balance = account_balance or self.account_balance
        if option_ask <= 0 or balance <= 0:
            return 0

        risk_pct             = self.effective_risk_pct(balance)
        total_risk_dollars   = balance * risk_pct                   # e.g. 3% of equity
        risk_per_contract    = option_ask * self.ORB_STOP_PCT * 100 # $ at risk per contract

        if risk_per_contract <= 0:
            return 0

        contracts = int(total_risk_dollars / risk_per_contract)

        # Notional cap: never spend more than 30% of equity on premium in
        # growth mode (20% in conservative mode) — prevents outsized exposure.
        # Computed here so the 1-contract minimum check can reference it.
        max_notional_pct = 0.30 if risk_pct > 0.01 else 0.20
        max_notional     = balance * max_notional_pct

        # Enforce minimum: allow 1 contract if the premium fits within the
        # notional cap (not the risk budget). Risk-budget floor was too strict —
        # e.g. SPY at $5.78/contract → $115 risk > $101 budget → always 0
        # even though $578 notional fits within a $609 cap at $2,030 balance.
        if contracts == 0 and (option_ask * 100) <= max_notional:
            contracts = 1

        while contracts > 1 and (option_ask * 100 * contracts) > max_notional:
            contracts -= 1

        # Determine human-readable tier label for audit log
        if risk_pct >= BOOTSTRAP_RISK_PCT:
            _tier_label = "Tier4_5pct"
        elif risk_pct >= GROWTH_MODE_RISK_PCT:
            _tier_label = "Tier3_3pct"
        elif risk_pct >= MID_TIER_RISK_PCT:
            _tier_label = "Tier2_2pct"
        else:
            _tier_label = "Tier1_1pct"

        logger.info(
            "position_sized",
            extra={
                "event":             "position_sized",
                "Risk_Tier_Used":    _tier_label,
                "risk_pct":          risk_pct,
                "account_balance":   round(balance, 2),
                "total_risk_budget": round(total_risk_dollars, 2),
                "risk_per_contract": round(risk_per_contract, 2),
                "option_ask":        round(option_ask, 4),
                "contracts":         contracts,
            },
        )
        return max(0, contracts)

    # ── Slippage-adjusted prices ──────────────────────────────────────────────

    def slippage_adjusted_entry(self, ask_price: float) -> float:
        """
        Worst-case fill price after 5% slippage on entry.
        We may pay up to 5% more than the quoted ask.

        Example: ask = $1.00 → effective entry = $1.05
        """
        return round(ask_price * (1.0 + self.SLIPPAGE_PCT), 4)

    def slippage_adjusted_target(self, target_price: float) -> float:
        """
        Worst-case exit fill after 5% slippage on exit (we receive 5% less).
        Applied to the stage-1 profit target to see if we still clear the R:R gate.

        Example: target = $1.50 → effective receipt = $1.425
        """
        return round(target_price * (1.0 - self.SLIPPAGE_PCT), 4)

    def max_affordable_premium(self, balance: Optional[float] = None) -> float:
        """
        Highest raw contract ASK price (pre-slippage) the bot can size to at
        least 1 contract under the current risk budget.

        This is the inverse of calculate_contracts(): instead of "how many
        contracts can I buy at this price", it answers "what's the most
        expensive contract I could buy 1 of without tripping SIZING_ZERO".

        Derivation:
          risk_per_contract = (ask * (1 + SLIPPAGE_PCT)) * ORB_STOP_PCT * 100
          risk_budget        = balance * effective_risk_pct(balance)
          1 contract affordable when risk_per_contract <= risk_budget, so:
          max_ask = risk_budget / ((1 + SLIPPAGE_PCT) * ORB_STOP_PCT * 100)

        Example: balance=$5,000, risk_per_trade=3% → risk_budget=$150
                 max_ask = 150 / (1.05 * 0.30 * 100) = 150 / 31.5 ≈ $4.76
        """
        bal      = balance or self.account_balance
        if bal <= 0:
            return 0.0

        risk_pct    = self.effective_risk_pct(bal)
        risk_budget = bal * risk_pct
        denom       = (1.0 + self.SLIPPAGE_PCT) * self.ORB_STOP_PCT * 100
        return round(risk_budget / denom, 2)

    # ── R:R evaluation (pre-entry gate) ──────────────────────────────────────

    def evaluate_rr(
        self,
        entry_price: float,
        trade_id: Optional[int] = None,
        n_contracts: int = 1,
        entry_volume_multiplier: float = 0.0,
    ) -> tuple[bool, dict]:
        """
        Calculate and audit the trade's Reward-to-Risk ratio BEFORE entry.

        Uses slippage-adjusted prices so the R:R reflects real-world fills:
          - Effective entry  = ask × 1.05  (we pay more)
          - Profit target    = entry × 1.50 × 0.95  (we receive less on exit)
          - Max loss         = entry × 0.30 × 1.05  (stop fill also slips)

        R:R = (profit_target - effective_entry) / (effective_entry - max_loss_price)
            = net_reward / net_risk

        A ratio below the effective minimum (effective_min_rr() — 1.2 for small
        accounts, 1.6 for professional/graduated accounts, per rr_ratio_mode)
        blocks the trade.

        Returns
        -------
        (allowed: bool, audit: dict)
            allowed  — True if the trade passes the R:R gate
            audit    — dict with full breakdown for structured logging
        """
        eff_entry   = self.slippage_adjusted_entry(entry_price)

        # Profit target: stage-1 gain (×1.50), exit slippage-adjusted
        raw_target  = eff_entry * (1.0 + self.ORB_STAGE1_GAIN)   # +50%
        eff_target  = self.slippage_adjusted_target(raw_target)

        # Max loss: stop at 30% below effective entry, slippage on exit adds cost
        sl_price    = eff_entry * (1.0 - self.ORB_STOP_PCT)
        # On a stop-out the exit also slips (bid side is lower)
        eff_sl      = self.slippage_adjusted_target(sl_price)     # receive 5% less

        net_reward  = eff_target - eff_entry
        net_risk    = eff_entry  - eff_sl

        if net_risk <= 0:
            # Degenerate case: effective stop is at or above entry (shouldn't happen)
            rr_ratio = 0.0
        else:
            rr_ratio = round(net_reward / net_risk, 3)

        # Dollar P&L projections for one contract (×100 multiplier)
        expected_win  = round(net_reward * n_contracts * 100, 2)
        expected_loss = round(-net_risk  * n_contracts * 100, 2)   # negative = loss

        _min_rr  = self.effective_min_rr()
        allowed  = rr_ratio >= _min_rr
        risk_pct = self.effective_risk_pct()

        # Human-readable risk tier label for structured log
        if risk_pct >= BOOTSTRAP_RISK_PCT:
            _tier_label = "Tier4_5pct"
        elif risk_pct >= GROWTH_MODE_RISK_PCT:
            _tier_label = "Tier3_3pct"
        elif risk_pct >= MID_TIER_RISK_PCT:
            _tier_label = "Tier2_2pct"
        else:
            _tier_label = "Tier1_1pct"

        audit = {
            # ── Mandatory 4-field audit signature ─────────────────────────────
            "Trade_ID":               trade_id,
            "Risk_Tier_Used":         _tier_label,
            "R_R_Ratio":              rr_ratio,
            "Min_RR_Required":        _min_rr,
            "Entry_Volume_Multiplier": round(entry_volume_multiplier, 2),
            # ── Full breakdown ─────────────────────────────────────────────────
            "entry_price":   round(entry_price, 4),
            "eff_entry":     round(eff_entry, 4),
            "eff_target":    round(eff_target, 4),
            "eff_stop":      round(eff_sl, 4),
            "Expected_Win":  expected_win,
            "Expected_Loss": expected_loss,
            "n_contracts":   n_contracts,
            "risk_pct":      risk_pct,
            "allowed":       allowed,
        }

        if allowed:
            logger.info(
                "Trade_Signal",
                extra={"event": "Trade_Signal", "Status": "ALLOWED", **audit},
            )
        else:
            audit["block_reason"] = "Trade_Blocked_Low_RR"
            logger.warning(
                "Trade_Blocked_Low_RR",
                extra={"event": "Trade_Blocked_Low_RR", **audit},
            )
            log_event(
                "WARNING", "risk",
                f"Trade_Blocked_Low_RR Trade_ID={trade_id} "
                f"R_R_Ratio={rr_ratio} Min_RR_Required={_min_rr} Risk_Tier_Used={_tier_label} "
                f"Entry_Volume_Multiplier={entry_volume_multiplier:.2f} "
                f"Expected_Win=${expected_win} Expected_Loss=${expected_loss}",
            )

        return allowed, audit

    # ── Dynamic stop tightening ───────────────────────────────────────────────

    def dynamic_stop_pct(
        self,
        entry_time: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> float:
        """
        Returns the current stop-loss percentage based on elapsed hold time.

        Tightening schedule (theta decay protection):
          0–14 min  → 20%  (ORB_STOP_PCT, initial — tightened from 30%)
          15–29 min → 15%
          ≥30 min   → floor (STOP_FLOOR_PCT = 10%)
          ≥45 min   → time-box fires for flat/losers; this method returns the floor

        The stop never falls below STOP_FLOOR_PCT (10%) to avoid noise exits.
        """
        if entry_time is None:
            return self.ORB_STOP_PCT

        now = now or datetime.utcnow()
        # Defensive tz normalization: strip tz from both sides if mixed,
        # so naive-vs-aware never raises TypeError.
        try:
            elapsed_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
        except TypeError:
            # One is tz-aware, other is naive — strip tz from both and retry
            _now_n = now.replace(tzinfo=None) if now.tzinfo else now
            _et_n  = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
            elapsed_minutes = max(0.0, (_now_n - _et_n).total_seconds() / 60)

        # Number of completed 15-minute intervals
        steps = int(elapsed_minutes / self.STOP_TIGHTEN_INTERVAL)
        tightened = self.ORB_STOP_PCT - (steps * self.STOP_TIGHTEN_STEP)
        return round(max(tightened, self.STOP_FLOOR_PCT), 4)

    def dynamic_stop_price(
        self,
        entry_price: float,
        entry_time: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> float:
        """Absolute stop price using the current dynamic stop percentage."""
        pct = self.dynamic_stop_pct(entry_time, now)
        return round(entry_price * (1.0 - pct), 4)

    def can_trade(self, account_balance: float, has_open_position: bool, now: Optional[datetime] = None) -> tuple[bool, str]:
        settings = get_settings()

        if not settings.get("trading_enabled", True):
            return False, "Kill-switch active"

        # ── Kill lock check (24h freeze after hard daily cap fires) ───────────
        locked, lock_reason = check_kill_lock()
        if locked:
            return False, lock_reason

        self.maybe_reset_for_new_day()
        self.account_balance = account_balance

        todays_pnl = get_todays_realized_pnl()

        # ── Daily loss enforcement ─────────────────────────────────────────────
        # Two thresholds:
        #   1. HARD CAP: 10% of equity — always enforced; triggers 24h kill lock.
        #   2. SOFT LIMIT: user-configurable (defaults to 10%, can be tightened).
        # Whichever is more conservative triggers first.
        hard_threshold = -(account_balance * DAILY_LOSS_HARD_CAP_PCT)   # always -10%
        soft_threshold = -(account_balance * settings.get("max_daily_loss_pct", 0.10))
        effective_threshold = max(hard_threshold, soft_threshold)        # max = least negative

        if self.daily_limit_hit or todays_pnl <= effective_threshold:
            if not self.daily_limit_hit:
                self.daily_limit_hit = True
                msg = (f"DAILY LOSS LIMIT: today_pnl=${todays_pnl:.2f} "
                       f"threshold=${effective_threshold:.2f}")
                log_event("WARNING", "risk", msg)
                logger.warning(
                    "daily_loss_limit_reached",
                    extra={
                        "event":             "daily_loss_limit_reached",
                        "today_pnl":         round(todays_pnl, 2),
                        "hard_threshold":    round(hard_threshold, 2),
                        "soft_threshold":    round(soft_threshold, 2),
                        "account_balance":   round(account_balance, 2),
                    },
                )
                # Trigger 24h kill lock if loss reached the hard cap
                if todays_pnl <= hard_threshold:
                    expires = set_kill_lock()
                    log_event(
                        "CRITICAL", "risk",
                        f"KILL LOCK SET — 10% hard cap breached. "
                        f"Trading frozen until {expires.strftime('%Y-%m-%d %H:%M')} UTC.",
                    )
            return False, f"Daily loss limit (today: ${todays_pnl:.2f})"

        if not self.is_trading_window(now):
            return False, "Outside trading window"

        if has_open_position:
            return False, "Position already open"

        from config import MIN_CONTRACT_COST
        if account_balance < MIN_CONTRACT_COST * 100:
            return False, f"Insufficient capital (${account_balance:.2f})"

        return True, "OK"

    def record_pnl(self, pnl: float, account_balance: float) -> None:
        settings       = get_settings()
        todays_pnl     = get_todays_realized_pnl()
        hard_threshold = -(account_balance * DAILY_LOSS_HARD_CAP_PCT)            # -10%
        soft_threshold = -(account_balance * settings.get("max_daily_loss_pct", 0.10))
        threshold      = max(hard_threshold, soft_threshold)   # use the tighter one

        if todays_pnl <= threshold:
            self.daily_limit_hit = True
            hit_hard_cap = todays_pnl <= hard_threshold
            msg = (f"DAILY LOSS LIMIT HIT: today=${todays_pnl:.2f} "
                   f"limit=${threshold:.2f} hard_cap={hit_hard_cap}")
            log_event("WARNING", "risk", msg)
            logger.warning(
                "daily_loss_limit_hit",
                extra={
                    "event":           "daily_loss_limit_hit",
                    "today_pnl":       round(todays_pnl, 2),
                    "threshold":       round(threshold, 2),
                    "hard_cap_hit":    hit_hard_cap,
                    "account_balance": round(account_balance, 2),
                    "trade_pnl":       round(pnl, 2),
                },
            )
            if hit_hard_cap:
                set_kill_lock()
            raise DailyLossLimitReached(msg)

    def stop_loss_price(self, entry_price: float) -> float:
        """ORB hard stop: 30% below entry premium."""
        return round(entry_price * (1.0 - self.ORB_STOP_PCT), 4)

    def structural_stop_price(
        self,
        entry_price: float,
        df,                       # pd.DataFrame of underlying OHLCV bars
        direction: str,           # "bullish" or "bearish"
        option_multiplier: float = 100.0,
    ) -> float:
        """
        Dynamic structural stop-loss based on market structure, not a fixed %.

        Logic:
          CALL (bullish): stop at the option premium implied by the most recent
            Swing Low in the underlying.  If underlying drops to the swing low,
            the option should be exited.

          PUT (bearish): stop at the option premium implied by the most recent
            Swing High in the underlying.  If underlying reclaims the swing high,
            the option should be exited.

        Conversion from underlying price move to option stop:
          The option is approximately delta-neutral at ~0.40 delta for ATM.
          We estimate the option's theoretical move from the structural level
          as:  option_stop = entry_price - |underlying_move × delta|

          If no swing is found (insufficient data), falls back to the static
          ORB_STOP_PCT (30%) as a safety net — never removes the hard stop.

        Returns the option stop price (always ≥ 0).
        """
        swing_price = find_structural_stop(df, direction)

        if swing_price is None:
            # No structural pivot found — use static 30% fallback
            logger.debug(
                "structural_stop_price: no swing found for %s — using ORB_STOP_PCT",
                direction,
            )
            return self.stop_loss_price(entry_price)

        # Estimate the current underlying price from the most recent bar
        try:
            underlying_current = float(df["close"].iloc[-1])
        except Exception:
            return self.stop_loss_price(entry_price)

        # Distance from current underlying price to the structural level
        underlying_move = abs(underlying_current - swing_price)

        # ATM option delta approximation: 0.40 (conservative for near-expiry)
        # option value change ≈ underlying_move × delta
        DELTA_APPROX = 0.40
        option_move  = underlying_move * DELTA_APPROX

        # Structural stop = entry - implied option move at the swing level
        struct_stop = entry_price - option_move

        static_stop = self.stop_loss_price(entry_price)   # 30% hard floor

        # Validity guard: if the structural swing is at or above the entry price
        # (i.e. the swing pivot is within noise distance of the current price),
        # the implied option stop would be ≥ entry — that would trigger immediately.
        # In that case discard the structural stop and fall back to the static 30%.
        # Previously used `min(struct_stop, entry_price * 0.99)` which set the stop
        # at 1% below entry — far too tight for options and caused 1-minute stop-outs.
        if struct_stop >= entry_price:
            result = static_stop
        else:
            result = max(static_stop, struct_stop)

        logger.debug(
            "structural_stop: direction=%s swing=%.4f underlying_move=%.4f "
            "option_move=%.4f entry=%.4f struct_stop=%.4f final=%.4f",
            direction, swing_price, underlying_move, option_move,
            entry_price, struct_stop, result,
        )
        return round(result, 4)

    def structural_stop_from_level(
        self,
        entry_price: float,
        underlying_current: float,
        stop_underlying: float,
    ) -> float:
        """
        Convert an explicit underlying stop level into an option stop price.

        Used when the entry signal carries entry_bar_high (PUT) or entry_bar_low
        (CALL) — the exact candle high/low that marks structural invalidation.

        Conversion:
          option_stop = entry_price − |stop_underlying − underlying_current| × delta
          ATM delta approximation = 0.40 (conservative for near-expiry options).

        The result is floored at the static 30% stop so we never set a stop that's
        more permissive than the hard risk limit.
        """
        underlying_move = abs(stop_underlying - underlying_current)
        DELTA_APPROX    = 0.40
        option_move     = underlying_move * DELTA_APPROX
        struct_stop     = entry_price - option_move
        static_stop     = self.stop_loss_price(entry_price)   # 30% floor
        if struct_stop >= entry_price:
            result = static_stop
        else:
            result = max(static_stop, struct_stop)
        logger.debug(
            "structural_stop_from_level: underlying_now=%.4f stop_level=%.4f "
            "underlying_move=%.4f option_move=%.4f entry=%.4f result=%.4f",
            underlying_current, stop_underlying, underlying_move, option_move,
            entry_price, result,
        )
        return round(result, 4)

    def structural_target_price(
        self,
        entry_price: float,
        underlying_current: float,
        direction: str,
        or_high: Optional[float] = None,
        or_low: Optional[float] = None,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
        vwap_upper2: Optional[float] = None,
        vwap_lower2: Optional[float] = None,
    ) -> float:
        """
        Dynamic profit target derived from chart structure, not a fixed +50%.

        Priority order for CALL (bullish) targets:
          1. Previous day high  — clean resistance, oft tested on gap days
          2. OR high × 2        — OR double-extension (institutional level)
          3. VWAP +2σ band      — mean-reversion resistance
          4. Static +50%        — fallback if no levels available

        Priority order for PUT (bearish) targets:
          1. Previous day low
          2. OR low − (OR range)
          3. VWAP −2σ band
          4. Static +50% fallback

        The chosen target must produce at least the minimum R:R ratio
        (effective_min_rr()) vs the structural stop. If it doesn't, falls back
        to the next candidate. If none qualify, returns the static +50%.

        Conversion from underlying target to option target:
          Same delta approximation (0.40) used in structural_stop_price.
        """
        DELTA_APPROX = 0.40

        def underlying_to_option_target(underlying_target: float) -> float:
            move = abs(underlying_target - underlying_current)
            return round(entry_price + move * DELTA_APPROX, 4)

        candidates: list[float] = []

        if direction == "bullish":
            # 1. Previous day high
            if prev_day_high and prev_day_high > underlying_current:
                candidates.append(prev_day_high)
            # 2. OR double extension
            if or_high and or_low:
                or_range   = or_high - or_low
                or_double  = or_high + or_range
                if or_double > underlying_current:
                    candidates.append(or_double)
            # 3. VWAP +2σ
            if vwap_upper2 and vwap_upper2 > underlying_current:
                candidates.append(vwap_upper2)
        else:  # bearish / PUT
            if prev_day_low and prev_day_low < underlying_current:
                candidates.append(prev_day_low)
            if or_high and or_low:
                or_range  = or_high - or_low
                or_double = or_low - or_range
                if or_double < underlying_current:
                    candidates.append(or_double)
            if vwap_lower2 and vwap_lower2 < underlying_current:
                candidates.append(vwap_lower2)

        # Sort candidates by proximity (nearest first — most achievable)
        candidates.sort(key=lambda c: abs(c - underlying_current))

        _min_rr    = self.effective_min_rr()
        static_sl  = self.stop_loss_price(entry_price)
        net_risk   = entry_price - static_sl

        for underlying_tgt in candidates:
            opt_tgt  = underlying_to_option_target(underlying_tgt)
            net_rew  = opt_tgt - entry_price
            rr       = net_rew / net_risk if net_risk > 0 else 0
            if rr >= _min_rr and opt_tgt > entry_price:
                logger.debug(
                    "structural_target: using %.4f (underlying %.4f) R:R=%.2f",
                    opt_tgt, underlying_tgt, rr,
                )
                return opt_tgt

        # No structural level qualified — fall back to static +50%
        return self.stage1_exit_price(entry_price)

    def stage1_exit_price(self, entry_price: float) -> float:
        """Price at which to sell the first 50% tranche (+50% gain)."""
        return round(entry_price * (1.0 + self.ORB_STAGE1_GAIN), 4)

    def take_profit_price(self, entry_price: float) -> float:
        """
        Kept for compatibility; in ORB mode stage1 handles the first exit
        and the remainder rides to the time-box or stop.
        Returns the stage-1 price for any code that still calls this method.
        """
        return self.stage1_exit_price(entry_price)

    def evaluate_exit_conditions(
        self,
        entry_price: float,
        current_price: float,
        entry_time: Optional[datetime] = None,
        now: Optional[datetime] = None,
        stage1_done: bool = False,
        stage1_be_price: Optional[float] = None,
        peak_price: Optional[float] = None,         # kept for API compatibility
        struct_stop_price: Optional[float] = None,  # entry_bar_high/low-derived option stop
        # Adaptive exit params — supplied by position_manager's bar analysis
        atr_trail_stop: Optional[float] = None,     # tighter of 1.5×ATR or swing stop (option price)
        vwap: Optional[float] = None,               # current underlying VWAP
        trend_dead: bool = False,                   # ADX<20 OR EMA stack misaligned
        direction: str = "bullish",                 # trade direction (for VWAP side check)
        rvol: float = 0.0,                          # current bar RVOL (for momentum-death check)
    ) -> tuple[bool, str]:
        """
        Adaptive exit engine — structure-driven, not time-driven.

        Exit hierarchy (checked in order):
          1. Structural stop  — entry_bar_high/low-derived option level (always on)
          2. ATR/swing trail  — tighter of 1.5×ATR below peak or last swing low/high
          3. VWAP + trend dead — breach + (ADX<20 OR EMA misalignment); NOT every dip
          4. Stage 1 target   — +50% option gain → partial exit signal
          5. Stage 2 trail    — entry×1.15 locked-profit floor on the runner
          6. Hard stop safety — 20% below entry (absolute net)
          7. Time cap (last resort) — 90m winners / 20m flat-losers

        Time caps are LAST RESORT only. Structure-based exits (2, 3) should fire
        before the clock ever becomes relevant for a correctly-entered trade.

        Parameters
        ----------
        entry_price      : option premium at fill
        current_price    : latest option mid-price
        entry_time       : datetime when trade opened (ET, tz-aware)
        now              : current datetime (ET, tz-aware)
        stage1_done      : True once the 50% partial exit has been executed
        stage1_be_price  : trail floor (entry×1.15) set after stage1 fires
        struct_stop_price: entry_bar_high/low-derived hard stop (option price level)
        atr_trail_stop   : ATR/swing trailing stop in option-price space
        vwap             : current underlying VWAP
        trend_dead       : True when ADX<20 or EMA stack is misaligned
        direction        : "bullish" (call) or "bearish" (put)
        """
        now = now or datetime.utcnow()

        # ── Elapsed time (for time-cap safety net only) ───────────────────────
        elapsed_minutes = 0.0
        if entry_time is not None:
            try:
                elapsed_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
            except TypeError:
                _now_n = now.replace(tzinfo=None) if now.tzinfo else now
                _et_n  = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
                elapsed_minutes = max(0.0, (_now_n - _et_n).total_seconds() / 60)

        # ── 1. Structural stop (entry bar high/low) ───────────────────────────
        if struct_stop_price is not None and current_price <= struct_stop_price:
            return True, (
                f"structural_stop_bar_high "
                f"(sl={struct_stop_price:.4f} current={current_price:.4f})"
            )

        # ── 2. ATR / swing trailing stop ──────────────────────────────────────
        # Replaces the old fixed-percentage dynamic stop.
        # Position manager ratchets this tighter as price moves in our favour.
        # Falls back to 20% hard stop if no ATR data available yet.
        if atr_trail_stop is not None:
            if current_price <= atr_trail_stop:
                return True, (
                    f"atr_trail_stop "
                    f"(trail={atr_trail_stop:.4f} current={current_price:.4f})"
                )
        else:
            # Fallback: 20% hard stop when bars not yet available
            hard_stop = entry_price * 0.80
            if current_price <= hard_stop:
                return True, f"hard_stop_20pct (sl={hard_stop:.4f} current={current_price:.4f})"

        # ── 2b. Volatility-adjusted profit lock (activates at +12% gain) ──────
        # Once the trade has ever been up 12% (tracked via peak_price from
        # position_manager), switch to tighter profit protection:
        #   - Use ATR trail if available (dynamic, wider on volatile days)
        #   - Hard fallback: entry + PROFIT_LOCK_TRAIL_PCT (3%) — never give
        #     back a +12% winner entirely, regardless of volatility.
        # This replaces waiting for a fixed +50% Stage-1 target with a dynamic
        # lock that captures 12–40% moves consistently.
        if not stage1_done and peak_price is not None:
            _profit_lock_trigger = entry_price * (1.0 + self.PROFIT_LOCK_PCT)
            if peak_price >= _profit_lock_trigger:
                # Trade has reached the lock threshold — protect the gain
                _lock_floor = entry_price * (1.0 + self.PROFIT_LOCK_TRAIL_PCT)
                # Use the higher of ATR trail or the fixed floor
                _effective_floor = (
                    max(_lock_floor, atr_trail_stop)
                    if atr_trail_stop is not None
                    else _lock_floor
                )
                if current_price <= _effective_floor:
                    return True, (
                        f"vol_adj_profit_lock "
                        f"(floor={_effective_floor:.4f} current={current_price:.4f} "
                        f"peak={peak_price:.4f} lock=+{self.PROFIT_LOCK_PCT:.0%})"
                    )

        # ── 3. VWAP breach + confirmed trend breakdown ────────────────────────
        # Only exits when BOTH conditions are met:
        #   a) Price has been below (call) or above (put) VWAP for ≥2 bars (tracked
        #      by position_manager via vwap_breached_bars counter → sets trend_dead)
        #   b) The trend is actually dead: ADX<20 OR EMA stack misaligned
        # This prevents exiting on every VWAP dip when momentum is still intact.
        if vwap is not None and trend_dead:
            vwap_broken = (
                (direction == "bullish" and current_price < vwap * 0.9990) or   # option well below VWAP equivalent
                (direction == "bearish" and current_price > vwap * 1.0010)
            )
            # For options, proxy the VWAP check via the already-computed trend_dead
            # flag from position_manager (which checked the underlying, not the option)
            # trend_dead=True means VWAP has been breached for ≥2 bars AND the trend
            # indicators confirm deterioration. Exit regardless of option price.
            _ = vwap_broken   # referenced above for clarity but trend_dead is the gate
            return True, f"vwap_trend_dead (trend_dead=True direction={direction})"

        # ── 4. Stage 1: +50% profit target ───────────────────────────────────
        if not stage1_done:
            s1 = self.stage1_exit_price(entry_price)
            if current_price >= s1:
                return True, f"stage1_50pct (target={s1:.4f} current={current_price:.4f})"

        # ── 5. Stage 2: locked-profit trail stop ─────────────────────────────
        if stage1_done and stage1_be_price is not None:
            if current_price <= stage1_be_price:
                return True, (
                    f"stage2_trail_stop "
                    f"(floor={stage1_be_price:.4f} current={current_price:.4f})"
                )

        # ── 6. Early momentum stop (first 20 min only, before stage 1) ───────
        # Fast failure detection: if the trade is down -12% within 20 min,
        # the setup failed. Exit before theta decay compounds the loss.
        if not stage1_done and elapsed_minutes <= EARLY_TIMEBOX_MIN:
            early_stop = entry_price * (1.0 - EARLY_STOP_PCT)
            if current_price <= early_stop:
                return True, (
                    f"early_momentum_stop_{round(EARLY_STOP_PCT*100)}pct "
                    f"(floor={early_stop:.4f} current={current_price:.4f} "
                    f"held={elapsed_minutes:.1f}min)"
                )

        # ── 7. Time caps — LAST RESORT ONLY ──────────────────────────────────
        # Structure-based exits (2, 3) should fire before these in a healthy trade.
        # These exist only as a safety net against zombie positions.

        # Momentum-death early exit: if RVOL has dropped below threshold AND
        # the trade is losing, institutional participation is gone. Exit before
        # the 60-min hard cap to stop theta decay on dead setups.
        # Both conditions required — dead RVOL alone doesn't kill a working trade.
        if (not stage1_done
                and rvol > 0.0
                and rvol < MOMENTUM_DEAD_RVOL
                and elapsed_minutes >= MOMENTUM_DEAD_MIN
                and current_price < entry_price):
            return True, (
                f"momentum_dead_exit "
                f"(rvol={rvol:.2f}<{MOMENTUM_DEAD_RVOL:.1f} losing held={elapsed_minutes:.1f}min)"
            )

        # Hard cap: 60 min for flat/losing trades (extended from 30 — momentum-death
        # check above kills dead weight before this fires for truly dead trades).
        if not stage1_done and elapsed_minutes >= EARLY_TIMEBOX_MIN:
            return True, (
                f"time_cap_loser_{EARLY_TIMEBOX_MIN}m "
                f"(held={elapsed_minutes:.1f}min — no momentum, killing theta)"
            )

        if stage1_done and elapsed_minutes >= self.ORB_TIME_BOX_WINNER:
            return True, f"time_cap_winner_90m (held={elapsed_minutes:.1f}min)"

        return False, "hold"

    def should_exit(
        self,
        entry_price: float,
        current_price: float,
        entry_time: Optional[datetime] = None,
        now: Optional[datetime] = None,
        stage1_done: bool = False,
        stage1_be_price: Optional[float] = None,
        # Legacy kwargs — kept so old call-sites don't break
        is_last_window: bool = False,
        peak_price: Optional[float] = None,
        struct_stop_price: Optional[float] = None,
        # Adaptive exit params (new)
        atr_trail_stop: Optional[float] = None,
        vwap: Optional[float] = None,
        trend_dead: bool = False,
        direction: str = "bullish",
        rvol: float = 0.0,
    ) -> tuple[bool, str]:
        """Preferred alias for evaluate_exit_conditions — used in position_manager."""
        return self.evaluate_exit_conditions(
            entry_price, current_price,
            entry_time=entry_time, now=now,
            stage1_done=stage1_done, stage1_be_price=stage1_be_price,
            struct_stop_price=struct_stop_price,
            atr_trail_stop=atr_trail_stop,
            vwap=vwap,
            trend_dead=trend_dead,
            direction=direction,
            rvol=rvol,
        )