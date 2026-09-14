"""
risk/sizing.py — Position sizing, risk %, and slippage-adjusted prices.

SizingMixin — mixed into RiskManager (risk/manager.py). Split out of risk.py
(2026-08-01, file-size cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

from config import (
    get_settings, get_risk_tier,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT, MID_TIER_RISK_PCT, CONSERVATIVE_RISK_PCT,
    GROWTH_RISK_BOUNDARY_BOOT, MIN_RR_RATIO_SMALL_ACCOUNT, MIN_RR_RATIO_PROFESSIONAL,
)

logger = logging.getLogger("celo_trader.risk")

# HIGH RISK WARNING fires at most ONCE PER SESSION (per service start).
_bootstrap_warn_shown: bool = False


class SizingMixin:
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
            global _bootstrap_warn_shown
            if not _bootstrap_warn_shown:
                _bootstrap_warn_shown = True
                _warn_msg = (
                    f"WARNING: HIGH RISK MODE ENABLED: {risk_pct:.1%} RISK PER TRADE: "
                    f"balance=${bal:,.2f} risk_budget=${bal * risk_pct:,.2f}"
                )
                logger.warning(_warn_msg)
                print(_warn_msg)   # also echoed to stdout / Streamlit console

        return risk_pct

    def effective_min_rr(self, balance: Optional[float] = None) -> float:
        """
        Return the active minimum R:R (reward:risk) gate threshold.

        Reads 'rr_ratio_mode' from user_settings.json fresh on every call.
        Modes: "auto" (default, balance-based switch at growth_risk_boundary_
        boot), "small_account" (always 1.2), "professional" (always 1.6).
        """
        bal      = balance or self.account_balance
        settings = get_settings()
        mode     = settings.get("rr_ratio_mode", "auto")

        if mode == "small_account":
            return MIN_RR_RATIO_SMALL_ACCOUNT
        if mode == "professional":
            return MIN_RR_RATIO_PROFESSIONAL

        boundary_boot = float(settings.get("growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT))
        if bal < boundary_boot:
            return MIN_RR_RATIO_SMALL_ACCOUNT
        return MIN_RR_RATIO_PROFESSIONAL

    def entry_risk_fraction(self, strategy_id: str | None = None) -> float:
        """Reviewed timers/structure exits do not enforce a premium stop.

        Budget their full debit. The generic stop is a planning assumption,
        not a guaranteed fill or maximum loss (gaps/slippage can exceed it).
        """
        from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
        return 1.0 if uses_v2_orb_execution_profile(strategy_id) else self.ORB_STOP_PCT

    def effective_notional_pct(self, balance: float, risk_pct: float | None = None) -> float:
        """Manual sizing uses the visible premium cap, never a hidden tier cap."""
        settings = get_settings()
        if settings.get("risk_per_trade") is not None:
            cap = float(settings.get("max_position_dollars_pct", 15)) / 100
            if not math.isfinite(cap) or not 0 < cap <= 1:
                raise ValueError("Maximum contract cost must be greater than 0% and at most 100%")
            return cap
        if bool(settings.get("growth_mode", False)) and balance < GROWTH_RISK_BOUNDARY_BOOT:
            return .45
        rate = self.effective_risk_pct(balance) if risk_pct is None else risk_pct
        return .30 if rate > CONSERVATIVE_RISK_PCT else .20

    def calculate_contracts(self, option_ask: float, account_balance: Optional[float] = None,
                            *, strategy_id: str | None = None) -> int:
        """
        ORB tiered risk model.

        Formula: floor( (equity × RISK_PCT) / (premium × ORB_STOP_PCT × 100) )
        RISK_PCT is 3% when growth_mode is ON and balance < $50k, else 1%.
        Both the risk budget and notional cap are ceilings, never minimums.
        Reviewed exits without a premium stop use full-debit risk instead.
        """
        balance = self.account_balance if account_balance is None else account_balance
        if not all(math.isfinite(x) and x > 0 for x in (option_ask, balance)):
            return 0

        risk_pct             = self.effective_risk_pct(balance)
        total_risk_dollars   = balance * risk_pct
        risk_per_contract    = option_ask * self.entry_risk_fraction(strategy_id) * 100

        if not math.isfinite(risk_pct) or not 0 < risk_pct <= 1 or risk_per_contract <= 0:
            return 0

        contracts = int(total_risk_dollars / risk_per_contract)

        # Bootstrap is based on account STATE (growth_mode ON + balance < $5k),
        # not the risk_pct value — manual overrides don't disable it.
        _s = get_settings()
        _in_bootstrap = bool(_s.get("growth_mode", False)) and balance < GROWTH_RISK_BOUNDARY_BOOT

        max_notional_pct = self.effective_notional_pct(balance, risk_pct)
        max_notional = balance * max_notional_pct

        contracts = min(contracts, int(max_notional / (option_ask * 100)))

        if _s.get("risk_per_trade") is not None:
            _tier_label = "Manual_user_setting"
        elif _in_bootstrap:
            _tier_label = "Tier4_bootstrap"
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

    def slippage_adjusted_entry(self, ask_price: float) -> float:
        """Worst-case fill price after 5% slippage on entry."""
        return round(ask_price * (1.0 + self.SLIPPAGE_PCT), 4)

    def slippage_adjusted_target(self, target_price: float) -> float:
        """Worst-case exit fill after 5% slippage on exit."""
        return round(target_price * (1.0 - self.SLIPPAGE_PCT), 4)

    def max_affordable_premium(self, balance: Optional[float] = None,
                               *, strategy_id: str | None = None) -> float:
        """
        Highest raw contract ASK price (pre-slippage) the bot can size to at
        least 1 contract under the current risk budget. Inverse of
        calculate_contracts(): max_ask = risk_budget / ((1+SLIPPAGE_PCT) *
        ORB_STOP_PCT * 100).
        """
        bal = self.account_balance if balance is None else balance
        if not math.isfinite(bal) or bal <= 0:
            return 0.0

        risk_pct    = self.effective_risk_pct(bal)
        risk_budget = bal * risk_pct
        if not math.isfinite(risk_pct) or not 0 < risk_pct <= 1:
            return 0.0
        notional_pct = self.effective_notional_pct(bal, risk_pct)
        premium = min(risk_budget / self.entry_risk_fraction(strategy_id), bal * notional_pct)
        # Round down: a rounded-up quote can exceed the budget by one cent.
        return math.floor(premium / (1.0 + self.SLIPPAGE_PCT)) / 100

    def dynamic_stop_pct(
        self,
        entry_time: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> float:
        """
        Current stop-loss percentage based on elapsed hold time (theta decay
        protection). Tightens by STOP_TIGHTEN_STEP every STOP_TIGHTEN_INTERVAL
        minutes, floored at STOP_FLOOR_PCT.
        """
        if entry_time is None:
            return self.ORB_STOP_PCT

        now = now or datetime.utcnow()
        try:
            elapsed_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
        except TypeError:
            _now_n = now.replace(tzinfo=None) if now.tzinfo else now
            _et_n  = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
            elapsed_minutes = max(0.0, (_now_n - _et_n).total_seconds() / 60)

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
