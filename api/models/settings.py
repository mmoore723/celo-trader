"""
api/models/settings.py — User-tunable trading settings schema.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class Settings(BaseModel):
    broker_provider: str = "alpaca"
    paper_trading: bool = True
    display_timezone: str = "America/New_York"
    risk_pct: float = Field(gt=0, le=100, allow_inf_nan=False)
    # True means the balance-based risk ladder is active.  `risk_pct` then
    # reports the currently effective tier rather than creating an override.
    risk_auto: bool = True
    growth_mode: bool
    flip_trading_enabled: bool
    max_concurrent_positions: int
    rr_ratio_mode: str
    watchlist: list[str]
    # Read-only from the dashboard's perspective. The server only fills this
    # after a reviewed real-quote validation; POST ignores client changes.
    validated_strategy_ids: list[str] = []
    # Only strategies promoted through real-quote backtesting are exposed.
    strategy_orb_pullback_v2_enabled: bool = True
    strategy_spy_trend_cont_v2_enabled: bool = True
    strategy_trend_cont_research_v1_enabled: bool = False
    enable_v2_afternoon_compression_breakout: bool = False
    enable_v2_gap_fill_rth: bool = False
    enable_v2_afternoon_reversal: bool = False
    enable_v2_spy_orb_rsi_macd_short: bool = False
    enable_v2_impulse_anchored_vwap_pullback: bool = False
    enable_research_ctx_orb_atr10_v2: bool = False
    enable_research_failed_range_v2: bool = False
    enable_research_qqq_trend_v2: bool = False
    enable_v2_vwap_pullback: bool = False
    enable_approved_v2_ema_pullback_rth: bool = False
    enable_approved_v2_fair_value_gap: bool = False
    enable_approved_v2_midday_breakdown: bool = False
    enable_approved_v2_opening_momentum_rth_exploratory: bool = False
    enable_approved_v2_orb_confirmed_breakout: bool = False
    enable_approved_v2_range_sweep_reclaim: bool = False
    enable_approved_v2_turtle_soup_rth: bool = False
    enable_approved_v2_vwap_reversion_rth: bool = False
    enable_approved_tv_supertrend_reversal_v4: bool = False
    enable_approved_v2_vwap_pullback: bool = False
    enable_approved_v2_trend_cont: bool = False
    enable_approved_v2_spy_trend_cont: bool = False
    enable_approved_v2_spy_afternoon_fvg: bool = False
    enable_approved_ctx_orb_nr7_or_inside: bool = False
    enable_approved_ctx_vwap_pullback_ker10_long: bool = False
    enable_approved_ctx_vwap_pullback_1030_displacement_long: bool = False
    enable_approved_ctx_1h_squeeze_macd_long: bool = False
    enable_approved_v2_orb_pullback: bool = False
    enable_approved_v2_tsla_two_leg_trend_pullback: bool = False
    strategy_spy_afternoon_fvg_v2_enabled: bool = True
    strategy_spy_failed_range_recovery_v2_enabled: bool = True
    strategy_tsla_two_leg_trend_pullback_v2_enabled: bool = True
    # These switches collect prospective evidence only. They cannot authorize
    # an order in paper or live mode.
    observe_ctx_orb_nr7_inside_enabled: bool = True
    observe_ctx_orb_atr10_enabled: bool = True
    observe_ctx_vwap_ker_enabled: bool = True
    observe_ctx_vwap_displacement_enabled: bool = True
    observe_ctx_squeeze_macd_enabled: bool = True
    # Exact, reconstructed historical strategies that are allowed to collect
    # evidence across the scanner universe. They never authorize orders.
    research_strategy_ids: list[str] = []
    opportunity_tier_enabled: bool = False  # observation-only lower-confidence research cohort; never changes account mode
    signal_only_mode: bool = False  # True = bot alerts but never places orders
    # ── Trade parameters (user-tunable without touching code) ─────────────────
    orb_stage1_gain_pct: float = 50.0   # Stage-1 profit target as % of entry
    orb_stop_loss_pct:   float = 20.0   # Option premium stop-loss as % of entry
    spread_gate_pct:     float = 8.0    # Max bid-ask spread as % of mid (tightened
                                          # from 25 on 2026-07-XX per config.py's
                                          # _DEFAULTS — this model default was stale,
                                          # fixed 2026-07-22 audit)
    vol_roc_threshold:   float = 0.50   # Volume ROC veto threshold
    daily_loss_hard_cap_pct: float = 10.0  # 2026-07-24: was hardcoded, non-
                                          # adjustable 10% (config.py's
                                          # DAILY_LOSS_HARD_CAP_PCT). Breaching
                                          # this freezes ALL trading for 24h
                                          # (kill lock) — see risk.py. Two
                                          # back-to-back trips (7/21, 7/22) on
                                          # this small account motivated making
                                          # it user-configurable. UI percentage,
                                          # e.g. 10.0 = 10%.
    min_grade_filter_enabled: bool = False  # 2026-07-24: blocks entries on tickers
                                          # graded below min_entry_grade (mirrors the
                                          # dashboard's premarket grade, which was
                                          # display-only until now). Off by default
                                          # like the other new gates added this session.
    min_entry_grade: str = "C"           # "A+" | "A" | "B" | "C" | "Watch" — cutoff
                                          # below which entries are blocked. Default
                                          # "C" blocks only the "Watch" grade.
    max_position_dollars_pct: float = Field(default=15.0, gt=0, le=100, allow_inf_nan=False)
                                          # This is what actually caps how much the
                                          # bot will spend on one contract's premium
                                          # (balance × this% ) — separate from risk_pct,
                                          # which only governs position SIZE/stop-loss
                                          # sizing, not the affordability cap. See the
                                          # BABA 10:02am incident, 2026-07-24: a valid
                                          # 77%-confidence signal got blocked here.
    # Compatibility readback only. Settings cannot switch exit engines;
    # reviewed strategies retain their versioned exit policy.
    simplified_exit_mode: bool = True
    mtf_confirmation_enabled: bool = True   # 2026-07-23: live 1Hour bias gate,
                                          # see trading/mtf_live_gate.py. Flipped
                                          # to ON by default 2026-07-31 per
                                          # explicit request — still can't be
                                          # backtested (live "as-of-now" fetch).
