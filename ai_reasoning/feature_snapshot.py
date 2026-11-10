"""
ai_reasoning/feature_snapshot.py — pure packaging functions for the AI
reasoning layer.

IMPORTANT: nothing in this file computes a NEW indicator. Every value here
was already calculated by the deterministic system before these functions
are called — strategy_router.py / router_gates.py for entries, risk.py's
should_exit() and position_manager.py's multi-timeframe trail logic for
exits. This module's only job is assembling those already-known values into
a small, JSON-safe dict the LLM can read and (eventually, for replay) the
database can store verbatim.

Keeping this separate from narrator.py means the "what data does the model
see" question has one answer, reviewable in one place, instead of being
scattered across two call sites in trading/entry.py and
trading/position_manager.py.
"""

from __future__ import annotations

from typing import Optional


def build_entry_snapshot(
    *,
    ticker: str,
    strategy_id: str,
    direction: str,
    confidence: float,
    rvol: float,
    contract_symbol: str,
    option_type: str,
    strike: float,
    expiry: str,
    n_contracts: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
    rr_ratio: float,
    paper: bool,
    trade_id: Optional[int] = None,
    signal_meta: Optional[dict] = None,
    exit_protection: Optional[dict] = None,
) -> dict:
    """
    Package one entry decision's already-computed data for the LLM prompt.

    Every argument here is a value trading/entry.py already had in hand at
    the moment the order was placed — the router's top signal (strategy,
    direction, confidence, rvol), the selected contract, the position size,
    and the stop/target the deterministic risk engine calculated.
    """
    return {
        "event":           "entry",
        "ticker":          ticker,
        "trade_id":        trade_id,
        "strategy_id":     strategy_id,
        "direction":       direction,
        "confidence":      round(confidence, 3),
        "rvol":            round(rvol, 2),
        "contract_symbol": contract_symbol,
        "option_type":     option_type,
        "strike":          strike,
        "expiry":          expiry,
        "n_contracts":     n_contracts,
        "entry_price":     round(entry_price, 4),
        "stop_price":      None if exit_protection and exit_protection.get('generic_reference_levels_only') else round(stop_price, 4),
        "target_price":    None if exit_protection and exit_protection.get('generic_reference_levels_only') else round(target_price, 4),
        "rr_ratio":        None if exit_protection and exit_protection.get('generic_reference_levels_only') else rr_ratio,
        "exit_protection": exit_protection,
        "paper_trading":   paper,
        "signal_meta":     signal_meta or {},
    }


def build_exit_snapshot(
    *,
    ticker: str,
    contract_symbol: str,
    direction: str,
    reason: str,
    entry_price: float,
    current_price: float,
    elapsed_minutes: float,
    mtf_notes: list,
    trade_id: Optional[int] = None,
    strategy_id: Optional[str] = None,
    peak_price: Optional[float] = None,
    min_price: Optional[float] = None,
) -> dict:
    """
    Package one exit decision's already-computed data for the LLM prompt.

    `reason` and `mtf_notes` come straight from risk.py's should_exit() and
    position_manager.py's `_mtf_notes` list (e.g. "1h_trend=WITH(2.5x)",
    "5m_rsi_exhaust=74(1.0x)") — the exact evidence the deterministic exit
    engine already used to make this call, not a re-derivation of it.
    """
    _pnl_pct = (
        round((current_price - entry_price) / entry_price * 100, 2)
        if entry_price else 0.0
    )
    return {
        "event":                "exit",
        "ticker":               ticker,
        "trade_id":             trade_id,
        "contract_symbol":      contract_symbol,
        "strategy_id":          strategy_id,
        "direction":            direction,
        "exit_reason":          reason,
        "entry_price":          round(entry_price, 4),
        "current_price":        round(current_price, 4),
        "pnl_pct":              _pnl_pct,
        "peak_price":           round(peak_price, 4) if peak_price is not None else None,
        "min_price":            round(min_price, 4) if min_price is not None else None,
        "elapsed_minutes":      round(elapsed_minutes, 1),
        "multi_timeframe_notes": list(mtf_notes or []),
    }


def build_decision_snapshot(
    *,
    ticker: str,
    strategy_id: str,
    direction: str,
    confidence: float,
    rvol: float,
    contract_symbol: str,
    option_type: str,
    strike: float,
    expiry: str,
    n_contracts: int,
    entry_price: float,
    rr_ratio: float,
    paper: bool,
    rsi: Optional[float] = None,
    macd_hist: Optional[list] = None,
    adx: Optional[float] = None,
    ema_aligned: Optional[bool] = None,
    trend_1h_bias: Optional[str] = None,
    trade_id: Optional[int] = None,
    candidate_id: Optional[str] = None,
) -> dict:
    """
    Package one PRE-entry decision-support review's already-computed data
    for the LLM prompt (phase 2 — ai_reasoning/decision_support.py).

    Same shape as build_entry_snapshot(), minus stop/target (not yet
    calculated at this point in trading/entry.py — decision support runs
    BEFORE the order exists, one step earlier than narrate_entry()) and PLUS
    the pre-entry multi-timeframe features (rsi, macd_hist, adx, ema_aligned,
    trend_1h_bias). Those come from trading/mtf_features.py — the SAME
    functions position_manager.py's exit engine already uses, so entry-side
    and exit-side readings of "is this ticker's momentum aligned right now"
    can never quietly drift out of sync with each other.

    Every MTF field is Optional. None means it genuinely wasn't computed at
    this point in the tick (see trading/entry.py's call site for which
    fields that applies to, e.g. trend_1h_bias is skipped to avoid a new
    blocking API call in the entry path) — the model should treat a None
    field as "unavailable", not as a neutral or zero reading.
    """
    return {
        "event":           "entry_review",
        "ticker":          ticker,
        "trade_id":        trade_id,
        "candidate_id":    candidate_id,
        "strategy_id":     strategy_id,
        "direction":       direction,
        "confidence":      round(confidence, 3),
        "rvol":            round(rvol, 2),
        "contract_symbol": contract_symbol,
        "option_type":     option_type,
        "strike":          strike,
        "expiry":          expiry,
        "n_contracts":     n_contracts,
        "entry_price":     round(entry_price, 4),
        "rr_ratio":        rr_ratio,
        "paper_trading":   paper,
        "rsi":             round(rsi, 2) if rsi is not None else None,
        "macd_hist":       [round(v, 5) for v in macd_hist] if macd_hist else None,
        "adx":             round(adx, 2) if adx is not None else None,
        "ema_aligned":     ema_aligned,
        "trend_1h_bias":   trend_1h_bias,
    }
