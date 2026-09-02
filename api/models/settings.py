"""
api/models/settings.py — User-tunable trading settings schema.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from pydantic import BaseModel


class Settings(BaseModel):
    broker_provider: str = "alpaca"
    paper_trading: bool = True
    display_timezone: str = "America/New_York"
    risk_pct: float
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
    max_position_dollars_pct: float = 15.0  # 2026-07-24: was hardcoded, no UI at all.
                                          # This is what actually caps how much the
                                          # bot will spend on one contract's premium
                                          # (balance × this% ) — separate from risk_pct,
                                          # which only governs position SIZE/stop-loss
                                          # sizing, not the affordability cap. See the
                                          # BABA 10:02am incident, 2026-07-24: a valid
                                          # 77%-confidence signal got blocked here.
    simplified_exit_mode: bool = True   # 2026-07-22: 3-rule exit (hard stop /
                                          # 3.0x chandelier trail / time cap) vs
                                          # the full 9+-condition engine. See
                                          # ab_test_exit_complexity.py.
    mtf_confirmation_enabled: bool = True   # 2026-07-23: live 1Hour bias gate,
                                          # see trading/mtf_live_gate.py. Flipped
                                          # to ON by default 2026-07-31 per
                                          # explicit request — still can't be
                                          # backtested (live "as-of-now" fetch).
