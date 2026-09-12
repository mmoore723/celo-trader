"""Entry gates and durable daily-loss enforcement, independent of research."""
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from config import get_settings, DAILY_LOSS_HARD_CAP_PCT
from database import log_event
from risk.kill_lock import check_kill_lock, set_kill_lock
from risk.db_helpers import get_todays_realized_pnl

logger = logging.getLogger("celo_trader.risk")


class DailyLossLimitReached(Exception):
    pass


class GuardMixin:
    def check_daily_loss(self, account_balance: float) -> str | None:
        """Use day-open for both checks; persist a halt before requesting exits."""
        from trading.state import get_user_state
        self.maybe_reset_for_new_day()
        # If storage was temporarily full, a recovered quote must not erase
        # the breach before the next successful persistence attempt.
        unpersisted = getattr(self, "_unpersisted_loss_halt", None)
        if unpersisted:
            set_kill_lock(**unpersisted["kwargs"])
            self._unpersisted_loss_halt = None
            return unpersisted["reason"]
        locked, reason = check_kill_lock()
        settings = get_settings()
        day_start = float(get_user_state().get("day_start_balance") or 0)
        hard_fraction = float(settings.get("daily_loss_hard_cap_pct", DAILY_LOSS_HARD_CAP_PCT * 100)) / 100
        soft_fraction = float(settings.get("max_daily_loss_pct", .10))
        if not math.isfinite(day_start) or day_start <= 0 or not math.isfinite(account_balance):
            raise ValueError("Positive day-open and finite current equity required for loss checks")
        if not all(math.isfinite(x) and 0 < x <= 1 for x in (hard_fraction, soft_fraction)):
            raise ValueError("Invalid daily-loss percentages; entries blocked")
        realized = get_todays_realized_pnl()
        if not math.isfinite(realized):
            raise ValueError("Daily realized P&L is unavailable")
        equity_change = account_balance - day_start
        hard = realized <= -day_start * hard_fraction or equity_change <= -day_start * hard_fraction
        soft = realized <= -day_start * soft_fraction
        # Keep checking a pending soft halt: losses during an unconfirmed
        # close can cross the hard limit and require the longer freeze.
        if locked and not hard:
            return reason
        if not hard and not soft:
            return None
        reason = (f"Daily loss limit — equity down ${max(0, -equity_change):.2f}; "
                  f"realized ${realized:.2f}; day-open ${day_start:.2f}")
        if hard:
            lock_kwargs = {}
        else:
            tomorrow = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            lock_kwargs = {"until": tomorrow.astimezone(timezone.utc).replace(tzinfo=None),
                           "reason": "daily_loss_soft_cap"}
        self.daily_limit_hit = True
        self._unpersisted_loss_halt = {"kwargs": lock_kwargs, "reason": reason}
        set_kill_lock(**lock_kwargs)
        self._unpersisted_loss_halt = None
        try:
            log_event("CRITICAL", "risk", reason + "; closing positions and blocking entries")
        except Exception:
            logger.exception("Could not log persisted daily-loss halt")
        return reason

    def can_trade(self, account_balance: float, has_open_position: bool,
                  now: Optional[datetime] = None) -> tuple[bool, str]:
        reason = self.check_daily_loss(account_balance)
        if reason:
            return False, reason
        if not get_settings().get("trading_enabled", True):
            return False, "Kill-switch active"
        self.account_balance = account_balance
        if not self.is_trading_window(now):
            return False, "Outside trading window"
        if has_open_position:
            return False, "Position already open"
        from config import MIN_CONTRACT_COST
        if account_balance < MIN_CONTRACT_COST * 100:
            return False, f"Insufficient capital (${account_balance:.2f})"
        return True, "OK"

    def record_pnl(self, pnl: float, account_balance: float) -> None:
        reason = self.check_daily_loss(account_balance)
        if reason:
            raise DailyLossLimitReached(reason)
