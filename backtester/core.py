"""
backtester/core.py — CoreMixin: Backtester construction (including the
live-tunable RiskManager knob sync) and contract-sizing math.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

from typing import Optional

import pandas as pd

from config import BACKTEST_MONTHS, STARTING_CAPITAL, _DEFAULTS
from risk import RiskManager


class CoreMixin:

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
        # Used for structural_stop_from_level()/should_exit() AND (2026-07-22)
        # the pre-entry evaluate_rr() gate — the same real risk.py engine live
        # trading calls (see backtest_exit_sim.py).
        self._risk = RiskManager()
        # BUG FIX 2026-07-22: risk.py's class default (ORB_STAGE1_GAIN=0.25) is
        # stale — live overrides it every tick from settings (orb_stage1_gain_pct,
        # default 50 in config.py's _DEFAULTS). backtest_exit_sim.py's own _risk
        # instance already got this same fix on 2026-07-21; this Backtester's
        # self._risk never did. Left uncorrected, evaluate_rr()'s rr_ratio is a
        # mathematically constant 0.781 (every term scales with entry price, so
        # only these two percentages determine it) — permanently below the
        # 1.2x/1.6x gate, blocking every single trade regardless of ticker,
        # strategy, or entry quality. This is why the R:R-gated backtest and
        # ab_test_structural_stop_mode.py runs came back with 0 trades.
        self._risk.ORB_STAGE1_GAIN = float(_DEFAULTS.get("orb_stage1_gain_pct", 50)) / 100.0
        self._risk.ORB_STOP_PCT    = float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0
        # BUG FIX 2026-07-22 (full-audit finding 1.1): the two lines above only
        # synced 2 of the 7 knobs live actually syncs every tick (see
        # trading/entry.py's "Sync user-editable trade parameters" block).
        # The other 5 were silently left at risk.py's raw class defaults —
        # correct today only by coincidence, not by design. If any of these
        # is ever changed via Settings, an unpatched backtester would keep
        # testing the OLD value forever with no error. Syncing all 7 here.
        self._risk.STAGE1_DYNAMIC_ENABLED     = bool(_DEFAULTS.get("stage1_dynamic_enabled", True))
        self._risk.STAGE1_ATR_TARGET_MULT     = float(_DEFAULTS.get("stage1_atr_target_mult", 2.0))
        self._risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(_DEFAULTS.get("stage1_floor_fraction_of_target", 75)) / 100.0
        self._risk.STAGE1_RVOL_FADE_THRESHOLD = float(_DEFAULTS.get("stage1_rvol_fade_threshold", 1.0))
        self._risk.STAGE1_MOMENTUM_REQUIRE_BOTH = bool(_DEFAULTS.get("stage1_momentum_require_both", True))
        # Entry-detection sources — populated by _prep_entry_sources() in run().
        self._df1m: Optional[pd.DataFrame] = None
        self._1m_day_start: dict = {}
        self._df5m_full: Optional[pd.DataFrame] = None
        self._5m_day_start: dict = {}

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
        if contracts == 0 and (entry_px * 100) <= max_notional:
            contracts = 1

        while contracts > 1 and (entry_px * 100 * contracts) > max_notional:
            contracts -= 1

        return max(0, contracts)

