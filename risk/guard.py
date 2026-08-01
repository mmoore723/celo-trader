"""
risk/guard.py — Pre-trade gate (kill lock, daily loss caps, trading window)
and post-trade daily-loss bookkeeping.

GuardMixin — mixed into RiskManager (risk/manager.py). Split out of risk.py
(2026-08-01, file-size cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from config import get_settings, DAILY_LOSS_HARD_CAP_PCT
from database import log_event
from risk.kill_lock import check_kill_lock, set_kill_lock
from risk.db_helpers import get_todays_realized_pnl

logger = logging.getLogger("celo_trader.risk")


class DailyLossLimitReached(Exception):
    pass


class GuardMixin:
    def can_trade(self, account_balance: float, has_open_position: bool, now: Optional[datetime] = None) -> tuple[bool, str]:
        settings = get_settings()

        if not settings.get("trading_enabled", True):
            return False, "Kill-switch active"

        locked, lock_reason = check_kill_lock()
        if locked:
            return False, lock_reason

        self.maybe_reset_for_new_day()
        self.account_balance = account_balance

        todays_pnl = get_todays_realized_pnl()

        # ── Daily loss enforcement ─────────────────────────────────────────
        # Two thresholds: HARD CAP (user-configurable %, default 10%,
        # triggers 24h kill lock) and the softer max_daily_loss_pct.
        _hard_cap_frac = settings.get("daily_loss_hard_cap_pct", DAILY_LOSS_HARD_CAP_PCT * 100) / 100.0
        hard_threshold = -(account_balance * _hard_cap_frac)
        soft_threshold = -(account_balance * settings.get("max_daily_loss_pct", 0.10))
        effective_threshold = max(hard_threshold, soft_threshold)   # max = least negative

        # ── Equity-based daily loss check (2026-07-15 audit) ────────────────
        # The DB-sum check above relies on the bot's own recorded fills, which
        # historically under-reported losses. This uses real Alpaca equity.
        _equity_drawdown = 0.0
        try:
            # get_user_state() resolves the ContextVar snapshot for the
            # thread's actual user — a global admin-only alias here would
            # make every user's kill-lock decision use ADMIN's balance.
            from trading.state import get_user_state
            _day_start = float(get_user_state().get("day_start_balance") or 0)
            if _day_start > 0 and account_balance > 0:
                _equity_drawdown = account_balance - _day_start
                if _equity_drawdown <= -(_day_start * _hard_cap_frac):
                    if not self.daily_limit_hit:
                        self.daily_limit_hit = True
                        expires = set_kill_lock()
                        log_event(
                            "CRITICAL", "risk",
                            f"KILL LOCK SET — Alpaca equity down "
                            f"${-_equity_drawdown:.2f} from day start "
                            f"(${_day_start:.2f} → ${account_balance:.2f}), breaching "
                            f"the 10% hard cap. Trading frozen until "
                            f"{expires.strftime('%Y-%m-%d %H:%M')} UTC.",
                        )
                    return False, (f"Daily loss limit — equity down "
                                   f"${-_equity_drawdown:.2f} from day start")
        except Exception as _eq_ex:
            logger.debug("equity drawdown check skipped: %s", _eq_ex)

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
                if todays_pnl <= hard_threshold:
                    expires = set_kill_lock()
                    log_event(
                        "CRITICAL", "risk",
                        f"KILL LOCK SET — 10% hard cap breached. "
                        f"Trading frozen until {expires.strftime('%Y-%m-%d %H:%M')} UTC.",
                    )
            return False, f"Daily loss limit (today: ${todays_pnl:.2f})"

        # NOTE 2026-07-15: per user instruction, NO per-day trade cap and NO
        # consecutive-loss halt. Only the loss caps above apply.

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
        _hard_cap_frac = settings.get("daily_loss_hard_cap_pct", DAILY_LOSS_HARD_CAP_PCT * 100) / 100.0
        hard_threshold = -(account_balance * _hard_cap_frac)
        soft_threshold = -(account_balance * settings.get("max_daily_loss_pct", 0.10))
        threshold      = max(hard_threshold, soft_threshold)

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
