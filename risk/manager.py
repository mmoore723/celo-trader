"""
risk/manager.py — RiskManager: assembles the risk engine from its mixins.

Split out of risk.py (2026-08-01, file-size cleanup) into a risk/ package.
No logic changed anywhere — every method just moved to a themed file and is
mixed back onto this one class via inheritance, so `self.X` calls resolve
identically regardless of which file actually defines X:
  risk/sizing.py     SizingMixin     — position sizing, risk %, slippage
  risk/rr.py         RRMixin         — pre-entry reward:risk gate
  risk/structural.py StructuralMixin — structure-based stop pricing
  risk/target.py     TargetMixin     — structure-based profit target
  risk/exits.py      ExitsMixin      — the adaptive exit engine
  risk/guard.py      GuardMixin      — can_trade gate + daily-loss bookkeeping
Class constants and the handful of trivial price helpers stay here since
every mixin reads them via self.
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime, date
from typing import Optional

from config import get_settings, STARTING_CAPITAL
from risk.sizing import SizingMixin
from risk.rr import RRMixin
from risk.structural import StructuralMixin
from risk.target import TargetMixin
from risk.exits import ExitsMixin
from risk.guard import GuardMixin, DailyLossLimitReached  # noqa: F401 — re-exported

logger = logging.getLogger("celo_trader.risk")


class RiskManager(SizingMixin, RRMixin, StructuralMixin, TargetMixin, ExitsMixin, GuardMixin):

    def __init__(self, account_balance: float = STARTING_CAPITAL, *, equity_reader=None):
        self.account_balance = account_balance
        self.equity_reader = equity_reader
        self.daily_limit_hit = False
        self._last_check_date = date.today()

    def maybe_reset_for_new_day(self) -> None:
        today = date.today()
        if today != self._last_check_date:
            self.daily_limit_hit = False
            self._last_check_date = today
            logger.info("New trading day — daily limit flag reset")

    def is_trading_window(self, now: Optional[datetime] = None) -> bool:
        # Balance-aware get_trading_windows() so the Phase 2 extended window
        # (09:45-11:30) automatically activates once the account clears $25k.
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
        """Dynamic percentage sizing and dollar caps based on account milestones."""
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

    # ── ORB Risk Model (tiered) ───────────────────────────────────────────
    # Position size = (Equity × RISK_PCT) / (Premium × ORB_STOP_PCT)
    ORB_STOP_PCT        = 0.20   # initial stop-loss = 20% of premium (tightened from 30%)
    ORB_RISK_PCT        = 0.01   # baseline risk % — used for R:R display / logging
    ORB_STAGE1_PCT      = 0.50   # sell 50% of contracts at stage-1 target
    ORB_STAGE1_GAIN     = 0.25   # +25% gain threshold — fail-open fallback only, see below

    # ── Dynamic stage1 trigger (2026-07-21) ───────────────────────────────
    # ab_test_stage1_target.py found the flat % above negative-expectancy at
    # 50/30/20% alike — replaced with a per-trade trigger: ATR-scaled target,
    # momentum fade (RSI+MACD), or volume fade (RVOL collapse), each gated by
    # a minimum-gain floor. Research basis: 10+ sources per CLAUDE.md rule 9,
    # 2026-07-21. Caller (position_manager.py / backtest_exit_sim.py)
    # precomputes atr_target_price + momentum_fading; this class never
    # touches raw bars/indicators.
    STAGE1_DYNAMIC_ENABLED     = True   # kill-switch — False reverts to the flat % above
    STAGE1_ATR_TARGET_MULT     = 2.0    # ATR multiplier for the dynamic target (1.5-2.5x per research)
    STAGE1_RVOL_FADE_THRESHOLD = 1.0    # RVOL below this after being elevated = crowd left
    # Target floor (2026-07-31): the loss side (initial_atr_stop) has always
    # been clamped to a 15-30%-of-premium floor. The target never had the
    # matching floor, so a quiet-bar ATR reading could size the target
    # smaller than the guaranteed minimum loss. Confirmed against every
    # audit report ever saved: stage1_atr_target won zero times, any
    # strategy, ever. This mirrors the stop side's clamp.
    STAGE1_TARGET_MIN_PCT      = 0.25   # target floored at +25% gain minimum
    # STAGE1_MOMENTUM_REQUIRE_BOTH (2026-07-31): OR -> AND — both RSI
    # exhaustion AND MACD fade must agree, not either alone (was tripping on
    # minor wobbles before the ATR target got a chance to fire).
    STAGE1_MOMENTUM_REQUIRE_BOTH      = True
    # STAGE1_FLOOR_FRACTION_OF_TARGET (raised 0.45 -> 0.75, 2026-07-31): the
    # fade check isn't eligible until a trade has covered this fraction of
    # the distance to the ATR target, so the real target gets a genuine shot
    # at finishing first on trades that are actually working.
    STAGE1_FLOOR_FRACTION_OF_TARGET   = 0.75
    # NOTE 2026-07-18: ORB_TIME_BOX is UNUSED (grepped, nothing reads it).
    # The real flat/losing time cap is config.EARLY_TIMEBOX_MIN. Left in
    # place rather than deleted — live-money code, not worth the tiny risk.
    ORB_TIME_BOX        = 45     # UNUSED — see note above
    ORB_TIME_BOX_WINNER = 90     # extended cap when stage1 IS done (let winners run)

    # ── 1.5x Profit-Factor enforcement ────────────────────────────────────
    MIN_RR_RATIO        = 1.6    # minimum reward-to-risk before entry is allowed
    SLIPPAGE_PCT        = 0.05   # 5% slippage buffer applied to entry & profit target

    # ── Dynamic stop tightening (theta decay protection) ──────────────────
    STOP_TIGHTEN_INTERVAL = 15   # minutes between each tightening step
    STOP_TIGHTEN_STEP     = 0.05 # 5pp reduction per step
    STOP_FLOOR_PCT        = 0.10 # never tighten below 10% (avoid noise-triggered exits)

    # ── Profit lock — disabled sentinels ───────────────────────────────────
    # The old profit lock (trigger +12%, floor +10%) produced 0.19:1 R:R.
    PROFIT_LOCK_PCT       = 0.50   # sentinel: same as stage 1 — effectively disabled
    PROFIT_LOCK_TRAIL_PCT = 0.40   # sentinel: floor well below stage 1 target

    def stop_loss_price(self, entry_price: float) -> float:
        """ORB hard stop: ORB_STOP_PCT below entry premium."""
        return round(entry_price * (1.0 - self.ORB_STOP_PCT), 4)

    def stage1_exit_price(self, entry_price: float) -> float:
        """Price at which to sell the first 50% tranche (+gain threshold)."""
        return round(entry_price * (1.0 + self.ORB_STAGE1_GAIN), 4)

    def take_profit_price(self, entry_price: float) -> float:
        """
        Kept for compatibility; in ORB mode stage1 handles the first exit
        and the remainder rides to the time-box or stop.
        """
        return self.stage1_exit_price(entry_price)
