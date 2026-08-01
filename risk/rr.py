"""
risk/rr.py — Pre-entry reward:risk gate.

RRMixin — mixed into RiskManager (risk/manager.py). Split out of risk.py
(2026-08-01, file-size cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT, MID_TIER_RISK_PCT
from database import log_event

logger = logging.getLogger("celo_trader.risk")


class RRMixin:
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

        A ratio below effective_min_rr() blocks the trade.

        Returns (allowed, audit) — audit is the full breakdown dict used for
        structured logging.
        """
        eff_entry = self.slippage_adjusted_entry(entry_price)

        raw_target = eff_entry * (1.0 + self.ORB_STAGE1_GAIN)
        eff_target = self.slippage_adjusted_target(raw_target)

        sl_price = eff_entry * (1.0 - self.ORB_STOP_PCT)
        eff_sl   = self.slippage_adjusted_target(sl_price)

        net_reward = eff_target - eff_entry
        net_risk   = eff_entry  - eff_sl

        if net_risk <= 0:
            rr_ratio = 0.0
        else:
            rr_ratio = round(net_reward / net_risk, 3)

        expected_win  = round(net_reward * n_contracts * 100, 2)
        expected_loss = round(-net_risk  * n_contracts * 100, 2)

        _min_rr  = self.effective_min_rr()
        allowed  = rr_ratio >= _min_rr
        risk_pct = self.effective_risk_pct()

        if risk_pct >= BOOTSTRAP_RISK_PCT:
            _tier_label = "Tier4_5pct"
        elif risk_pct >= GROWTH_MODE_RISK_PCT:
            _tier_label = "Tier3_3pct"
        elif risk_pct >= MID_TIER_RISK_PCT:
            _tier_label = "Tier2_2pct"
        else:
            _tier_label = "Tier1_1pct"

        audit = {
            "Trade_ID":               trade_id,
            "Risk_Tier_Used":         _tier_label,
            "R_R_Ratio":              rr_ratio,
            "Min_RR_Required":        _min_rr,
            "Entry_Volume_Multiplier": round(entry_volume_multiplier, 2),
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
