"""
config/defaults.py — _DEFAULTS: every user-settable trading parameter and
its hardcoded fallback value, with the full audit-history comment trail.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from config.env_keys import ALPACA_PAPER

_DEFAULTS = {
    # ── Risk Per Trade Override ────────────────────────────────────────────────
    # None = automatic (balance-based tier logic).
    # Set to 0.01, 0.03, or 0.05 to pin a specific risk % regardless of balance.
    "risk_per_trade": None,
    "max_concurrent_positions": 2,

    # ── Growth Mode ────────────────────────────────────────────────────────────
    "growth_mode":               False,     # OFF by default — user enables in Risk Settings
    "growth_risk_boundary_boot": 5_000.0,  # Tier 4 → Tier 3 transition (5% → 3%)
    "growth_risk_boundary_low":  25_000.0, # Tier 3 → Tier 2 transition (3% → 2%)
    "growth_risk_boundary":      50_000.0, # Tier 2 → Tier 1 transition (2% → 1%)
    "kill_lock_hours":           24,        # hours to lock after daily hard cap fires

    # ── R:R Threshold Mode ─────────────────────────────────────────────────────
    # "auto" (default) = balance-based switch: 1.2 R:R while < growth_risk_boundary_boot
    #   (sub-$5k bootstrap tier), auto-switches to 1.6 R:R once balance crosses it.
    # "small_account" = always 1.2 R:R. "professional" = always 1.6 R:R.
    "rr_ratio_mode":             "auto",

    # Dynamic Risk Ladder — no hard ceiling, scales with account
    "phase_1_aggressive_pct":   0.15,    # 15% sizing under $25k
    "phase_2_moderate_pct":     0.08,    # 8%  sizing $25k-$100k
    "phase_3_conservative_pct": 0.03,    # 3%  sizing above $100k
    "phase_2_boundary":         25000.0,
    "phase_3_boundary":         100000.0,
    "phase_3_hard_cap_usd":     5000.0,  # max single trade above $100k

    # Legacy sizing keys (used by dashboard sliders)
    "max_position_size_pct":    0.15,
    "max_position_dollars_pct": 15,
    "max_position_dollars":     750,

    # Exit parameters — max_daily_loss_pct is the user-adjustable soft limit.
    "max_daily_loss_pct":    0.10,   # default 10% — matches hard cap
    # Hard cap that triggers the 24h kill lock (trading fully frozen). Stored as
    # a UI percentage (10.0 = 10%), unlike max_daily_loss_pct above which is a
    # raw decimal — matches the other Settings-page fields' convention (see
    # orb_stage1_gain_pct etc. below). Added 2026-07-24 after two back-to-back
    # kill locks (7/21, 7/22) on a small account — was previously hardcoded and
    # non-adjustable (config.py's DAILY_LOSS_HARD_CAP_PCT).
    "daily_loss_hard_cap_pct": 10.0,

    # Minimum-grade entry filter — 2026-07-24, off by default. See
    # router_gates.py::apply_grade_filter(). Grades mirror the dashboard's
    # premarket report (A+/A/B/C/Watch); "C" cutoff blocks only "Watch".
    "min_grade_filter_enabled": False,
    "min_entry_grade": "C",
    "stop_loss_pct":         0.50,
    "take_profit_pct":       1.00,
    "trail_stop_pct":        0.25,

    # ── ORB trade parameters (user-editable via Settings → Trade Parameters) ────
    # These override the class constants in risk.py and the hardcoded gates in
    # entry.py / strategy_router.py so the user can tune live without touching code.
    "orb_stage1_gain_pct":   50,    # Stage-1 profit target as % of entry (50 = +50%)
                                    # NOTE 2026-07-21: this flat % is now only the FAIL-OPEN
                                    # fallback (used when ATR data is missing). The primary
                                    # stage-1 trigger is dynamic — see stage1_dynamic_enabled
                                    # below. Research basis: ab_test_stage1_target.py found
                                    # 50/30/20% all negative expectancy, ~0 winners ever
                                    # reached the static target.
    "orb_stop_loss_pct":     20,    # Option premium stop-loss as % of entry (20 = -20%)
    "stage1_dynamic_enabled":      True,   # ATR/momentum/volume-based stage1 trigger (kill-switch)
    "stage1_atr_target_mult":      2.0,    # ATR multiplier for the dynamic target (1.5-2.5x per research)
    # 2026-07-31: was a flat % of premium (stage1_min_lock_floor_pct=10) — now
    # a fraction of the distance to the ATR target, so it scales with
    # volatility like the target itself does. See risk.py's STAGE1_
    # FLOOR_FRACTION_OF_TARGET docstring for the diagnosis.
    "stage1_floor_fraction_of_target": 75, # % of the ATR-target distance required before momentum/volume fade can lock early (2026-07-31: raised from 45 -- see risk.py)
    "stage1_rvol_fade_threshold":  1.0,    # RVOL below this (after being elevated) = crowd left, lock early
    "stage1_momentum_require_both": True,  # 2026-07-31: was False (OR) — requires BOTH RSI exhaustion AND MACD fade
    # 2026-07-15 audit: 25% was far too loose — a 25% spread is an instant ~12%
    # loss at entry. 8% max keeps round-trip spread cost survivable.
    "spread_gate_pct":       8,     # Max bid-ask spread as % of mid (8 = 8%)
    "vol_roc_threshold":     0.50,  # Volume ROC veto threshold (0.50 = 50% of prior vol)
    # 2026-07-22: ab_test_exit_complexity.py — stripped-down 3-rule exit
    # (hard stop / 3.0x chandelier trail / 1 time cap) beat the full 9+-
    # condition engine on realized R:R (1.17-1.29x vs 0.20-0.27x) at roughly
    # the same avg loss but 4.3x bigger avg wins, stacked with prior_swing.
    # Default True = simplified path live. False = fall back to the full
    # risk.py engine (trading/position_manager.py's should_exit() call).
    "simplified_exit_mode":  True,

    # 2026-07-23 (Gap 3, professional-strategy-alignment audit): live 1Hour
    # MTF confirmation gate — see trading/mtf_live_gate.py + router_gates.py's
    # apply_mtf_confirmation(). OFF by default because, unlike every other
    # toggle in this file, it can't be validated against the historical
    # backtester (it depends on a live "as-of-now" API fetch, not replayable
    # multi-day data) — watch it in signal_only_mode before trusting it.
    "mtf_confirmation_enabled": True,

    # Server-reviewed scope. A per-strategy account toggle is still required
    # before a reviewed rule can enter in either paper or live mode; this list
    # only prevents a browser from enabling an unrelated strategy by sending
    # an arbitrary ID.
    "validated_strategy_ids": ["V2_ORB_PULLBACK", "V2_SPY_TREND_CONT", "V2_SPY_AFTERNOON_FVG", "V2_FAILED_OR_BREAK_VWAP_REVERSION", "V2_TSLA_TWO_LEG_TREND_PULLBACK"],
    "strategy_orb_pullback_v2_enabled": True,
    # Passed the separately held-back SPY option-quote data at the reviewed
    # 30-minute same-contract exit. Enable it for new accounts just as the
    # reviewed TSLA rules are enabled below; users retain the Settings switch.
    "strategy_spy_trend_cont_v2_enabled": True,
    "strategy_spy_afternoon_fvg_v2_enabled": True,
    # Passed the declared selection, validation, and untouched holdout gates.
    # Enabled by default alongside the other reviewed strategies.
    "strategy_spy_failed_range_recovery_v2_enabled": True,
    # Reviewed TSLA paid-quote strategy. Enabled by default; individual users
    # can still turn it off from Settings in either account mode.
    # Earlier 200 TSLA option-quote sessions selected this exact one-minute
    # two-leg rule; 51 untouched later sessions also passed. Default ON.
    "strategy_tsla_two_leg_trend_pullback_v2_enabled": True,

    # Exact context-strategy suggestions are prospective research observers.
    # ON means collect real candidates and option quotes; these flags have no
    # route to paper or live orders.  The catalog enforces that invariant.
    "observe_ctx_orb_nr7_inside_enabled": True,
    "observe_ctx_orb_atr10_enabled": True,
    "observe_ctx_vwap_ker_enabled": True,
    "observe_ctx_vwap_displacement_enabled": True,
    "observe_ctx_squeeze_macd_enabled": True,

    # Paper-only lower-confidence research cohort. Disabled after the 2026-08-02
    # locked-holdout panel increased activity while worsening aggregate results.
    # Candidates remain journaled as `opportunity` for separate evidence.
    "opportunity_tier_enabled": False,
    # QQQ research is intentionally off while TSLA's already-paid real quote
    # sample is being evaluated. It has no order path when enabled.
    "qqq_opening_research_enabled": False,
    # Learning ledger: evaluate every built-in strategy in paper mode even
    # when it is not approved to place an order.  These candidates are marked
    # observed_only and can never reach contract selection or execution.
    "shadow_observe_all_strategies": True,
    # Reconstructed, deterministic research-engine strategies. These run on
    # every ticker collected by the research worker and have no order path.
    "research_strategy_ids": [
        "V2_AFTERNOON_REVERSAL", "V2_EMA_PULLBACK_RTH", "V2_FAIR_VALUE_GAP",
        "V2_GAP_FILL_RTH", "V2_MIDDAY_BREAKDOWN",
        "V2_OPENING_MOMENTUM_RTH_EXPLORATORY", "V2_ORB_CONFIRMED_BREAKOUT",
        "V2_RANGE_SWEEP_RECLAIM",
        "V2_SPY_ORB_RSI_MACD_SHORT", "V2_TREND_CONT", "V2_TURTLE_SOUP_RTH",
        "V2_VWAP_PULLBACK", "V2_VWAP_REVERSION_RTH", "TV_SUPERTREND_REVERSAL_V4",
    ],

    # Filters
    "volume_filter_enabled":   True,
    "volume_filter_multiplier": 2.0,
    "earnings_filter_enabled": True,
    "require_mtf_agreement":   True,
    "max_bid_ask_spread":      0.10,   # $0.10 max spread — realistic for liquid options

    # System
    # Alpaca remains the deployed provider until the Tradier readiness gate
    # confirms account balance, positions, orders, clock, and fresh market data.
    # Switching this value changes entries AND exits together in broker.factory.
    "broker_provider":      "alpaca",
    "email_alerts_enabled": False,
    "paper_trading":        ALPACA_PAPER,
    "alpaca_data_plan":     "free",   # "free" = IEX regular session; "premium" = SIP + pre-market
    "trading_enabled":      True,
    "flip_trading_enabled": True,
    "last_known_balance":   0.0,
    "theme":                "light",
    "tax_reserve_pct":      25,
    "monthly_income_goal":  6000,
}
