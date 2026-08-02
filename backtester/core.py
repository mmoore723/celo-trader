"""
backtester/core.py — CoreMixin: Backtester construction (including the
live-tunable RiskManager knob sync) and contract-sizing math.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

from datetime import date
from typing import Optional

import pandas as pd

from config import (
    BACKTEST_MONTHS, STARTING_CAPITAL, get_settings,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT, MID_TIER_RISK_PCT,
    CONSERVATIVE_RISK_PCT, GROWTH_RISK_BOUNDARY_BOOT,
    GROWTH_RISK_BOUNDARY_LOW, GROWTH_RISK_BOUNDARY,
)
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
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        self.alpaca            = alpaca
        self.ticker            = ticker
        self.months            = months
        self.capital           = starting_capital
        self.direction         = direction
        self.risk_pct_override = risk_pct   # None → live 4-tier ladder
        self.start_date        = start_date
        self.end_date          = end_date
        self.trades: list[dict] = []
        # Freeze settings once so a running replay is reproducible and cannot
        # silently change when a dashboard setting is saved mid-run.
        self.backtest_settings = get_settings()
        # Match trading/entry/tick.py: a normal dashboard backtest must only
        # replay strategies currently enabled for paper/live trading. A/B
        # harnesses can explicitly replace this set for a hypothetical test.
        _strategy_settings = (
            ("INST_ORB", "strategy_orb_enabled", True),
            ("VWAP_PB", "strategy_vwap_enabled", True),
            ("FVG", "strategy_fvg_enabled", True),
            ("IFVG", "strategy_ifvg_enabled", True),
            ("MID_BRK", "strategy_mid_enabled", False),
            ("AFT_REV", "strategy_aft_enabled", True),
            ("TREND_CONT", "strategy_tcont_enabled", True),
            ("GAP_GO", "strategy_gapgo_enabled", True),
            ("LIQ_SWEEP", "strategy_liqsweep_enabled", True),
        )
        self.enabled_strategies = {
            strategy_id for strategy_id, key, default in _strategy_settings
            if bool(self.backtest_settings.get(key, default))
        }
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
        self._risk.ORB_STAGE1_GAIN = float(self.backtest_settings.get("orb_stage1_gain_pct", 50)) / 100.0
        self._risk.ORB_STOP_PCT    = float(self.backtest_settings.get("orb_stop_loss_pct", 20)) / 100.0
        self.ORB_STOP_PCT          = self._risk.ORB_STOP_PCT
        # BUG FIX 2026-07-22 (full-audit finding 1.1): the two lines above only
        # synced 2 of the 7 knobs live actually syncs every tick (see
        # trading/entry.py's "Sync user-editable trade parameters" block).
        # The other 5 were silently left at risk.py's raw class defaults —
        # correct today only by coincidence, not by design. If any of these
        # is ever changed via Settings, an unpatched backtester would keep
        # testing the OLD value forever with no error. Syncing all 7 here.
        self._risk.STAGE1_DYNAMIC_ENABLED     = bool(self.backtest_settings.get("stage1_dynamic_enabled", True))
        self._risk.STAGE1_ATR_TARGET_MULT     = float(self.backtest_settings.get("stage1_atr_target_mult", 2.0))
        self._risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(self.backtest_settings.get("stage1_floor_fraction_of_target", 75)) / 100.0
        self._risk.STAGE1_RVOL_FADE_THRESHOLD = float(self.backtest_settings.get("stage1_rvol_fade_threshold", 1.0))
        self._risk.STAGE1_MOMENTUM_REQUIRE_BOTH = bool(self.backtest_settings.get("stage1_momentum_require_both", True))
        # Live defaults to this mode. A/B scripts may still override it after
        # construction, but a normal dashboard backtest must test the live bot.
        self.SIMPLIFIED_EXIT_MODE = bool(self.backtest_settings.get("simplified_exit_mode", True))
        # The lower-confidence cohort is experimental and paper-only.  Keep
        # its scheduling rule behind the exact same setting as live execution
        # so a normal dashboard replay cannot test a different bot.
        self.OPPORTUNITY_SCHEDULER_ENABLED = bool(
            self.backtest_settings.get("paper_trading", True)
            and self.backtest_settings.get("opportunity_tier_enabled", False)
        )
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
            risk_pct = self._effective_risk_pct(balance)

        total_risk        = balance * risk_pct
        risk_per_contract = entry_px * self.ORB_STOP_PCT * 100   # $ at risk per contract

        if risk_per_contract <= 0:
            return 0

        contracts = int(total_risk / risk_per_contract)

        boot_boundary = float(self.backtest_settings.get(
            "growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT,
        ))
        in_bootstrap = bool(self.backtest_settings.get("growth_mode", False)) and balance < boot_boundary
        max_notional_pct = 0.45 if in_bootstrap else (0.30 if risk_pct > CONSERVATIVE_RISK_PCT else 0.20)
        max_notional     = balance * max_notional_pct

        while contracts > 1 and (entry_px * 100 * contracts) > max_notional:
            contracts -= 1

        if in_bootstrap:
            if contracts < 2 and (entry_px * 100 * 2) <= max_notional:
                contracts = 2
            elif contracts == 0 and (entry_px * 100) <= max_notional:
                contracts = 1
        elif contracts == 0 and (entry_px * 100) <= max_notional:
            contracts = 1

        return max(0, contracts)

    def _effective_risk_pct(self, balance: float) -> float:
        """Snapshot equivalent of config.get_risk_tier() for this replay."""
        override = self.backtest_settings.get("risk_per_trade")
        try:
            if override is not None and 0 < float(override) <= 0.25:
                return float(override)
        except (TypeError, ValueError):
            pass
        if not self.backtest_settings.get("growth_mode", False):
            return CONSERVATIVE_RISK_PCT
        boot = float(self.backtest_settings.get("growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT))
        low = float(self.backtest_settings.get("growth_risk_boundary_low", GROWTH_RISK_BOUNDARY_LOW))
        high = float(self.backtest_settings.get("growth_risk_boundary", GROWTH_RISK_BOUNDARY))
        if balance < boot:
            return BOOTSTRAP_RISK_PCT
        if balance < low:
            return GROWTH_MODE_RISK_PCT
        if balance < high:
            return MID_TIER_RISK_PCT
        return CONSERVATIVE_RISK_PCT
