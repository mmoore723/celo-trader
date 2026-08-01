"""
trading/annotations/emit.py — emit_annotation(), emit_signal_annotation().

Split out of the old single trading/annotations.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

from typing import Any

from trading.annotations.constants import _MAX_ANNOTATIONS, _COLORS


def emit_annotation(
    ticker: str,
    ann_type: str,              # "hline" | "zone" | "marker"
    strategy: str,              # e.g. "FVG", "veto", "stage1"
    label: str,                 # display text
    ts: str,                    # ISO datetime — when the bot detected it
    color: str | None = None,
    price: float | None = None,        # for hline + marker
    price_low: float | None = None,    # for zone (bottom edge)
    price_high: float | None = None,   # for zone (top edge)
    direction: str | None = None,      # "bullish" | "bearish"
) -> None:
    """Append one chart annotation to this user's state for the given ticker.

    FIX: previously wrote to the global LIVE_STATE alias (admin's state) via
    a late import — every user's bot-detected chart overlays landed on
    admin's dashboard instead of their own. Now resolves the calling user's
    own state fresh (ContextVar-based — see trading/state.py::get_user_state).
    """
    # Late import — avoids circular dependency at module load time
    from trading.state import get_user_state  # noqa: PLC0415
    _US = get_user_state()

    # Resolve color: explicit > strategy+direction > strategy alone > default
    _key = f"{strategy}_{direction}" if direction else strategy
    resolved = color or _COLORS.get(_key) or _COLORS.get(strategy) or _COLORS["default"]

    ann: dict[str, Any] = {
        "id":        f"{strategy}_{ts}",
        "type":      ann_type,
        "strategy":  strategy,
        "label":     label,
        "ts":        ts,
        "color":     resolved,
        "direction": direction,
    }
    if price is not None:
        ann["price"] = round(float(price), 4)
    if price_low is not None:
        ann["price_low"] = round(float(price_low), 4)
    if price_high is not None:
        ann["price_high"] = round(float(price_high), 4)

    if "chart_annotations" not in _US:
        _US["chart_annotations"] = {}

    bucket: list = _US["chart_annotations"].setdefault(ticker.upper(), [])
    bucket.append(ann)

    # Cap — drop oldest entries
    if len(bucket) > _MAX_ANNOTATIONS:
        _US["chart_annotations"][ticker.upper()] = bucket[-_MAX_ANNOTATIONS:]


def emit_signal_annotation(ticker: str, sig: Any, today: Any) -> None:
    """
    Translate a strategy Signal into one or more chart overlays. Called by
    strategy_router immediately after a strategy fires so the drawing
    appears on the frontend chart in real time.

    Per-strategy rules:
      FVG / IFVG  → zone band (gap_low … gap_high)
      BOS_MSS     → hline at bos_level
      TREND_CONT  → hline at the swing re-entry level (lh_price or hl_price)
      INST_ORB    → hline at prior swing high/low that was broken
      AFT_REV     → hline at prior swing high/low
      VWAP_PB / MID_BRK → marker only (VWAP line already on chart)
    All strategies also emit a candle marker showing where the signal fired.
    """
    meta   = sig.meta or {}
    ts_str = (sig.trigger_bar.isoformat()
              if hasattr(sig.trigger_bar, "isoformat") else str(sig.trigger_bar))
    arrow  = "↑" if sig.direction == "bullish" else "↓"

    _last_close = float(today.iloc[-1]["close"]) if not today.empty else None

    if sig.strategy_id in ("FVG", "IFVG"):
        gl = meta.get("gap_low")
        gh = meta.get("gap_high")
        if gl is not None and gh is not None:
            emit_annotation(
                ticker, "zone", sig.strategy_id,
                label=f"{sig.strategy_id} {arrow}  {sig.confidence:.0%}",
                ts=ts_str, direction=sig.direction,
                price_low=gl, price_high=gh,
            )

    elif sig.strategy_id == "BOS_MSS":
        lvl = meta.get("bos_level")
        if lvl:
            emit_annotation(ticker, "hline", "BOS_MSS",
                             label=f"BOS {arrow}  {sig.confidence:.0%}",
                             ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "TREND_CONT":
        lvl = meta.get("lh_price") or meta.get("hl_price")
        if lvl:
            emit_annotation(ticker, "hline", "TREND_CONT",
                             label=f"TC {arrow}  {sig.confidence:.0%}",
                             ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "INST_ORB":
        lvl = meta.get("prev_swing_high") or meta.get("prev_swing_low")
        if lvl:
            emit_annotation(ticker, "hline", "INST_ORB",
                             label=f"ORB {arrow}  {sig.confidence:.0%}",
                             ts=ts_str, price=lvl, direction=sig.direction)

    elif sig.strategy_id == "AFT_REV":
        lvl = meta.get("prev_swing_high") or meta.get("prev_swing_low")
        if lvl:
            emit_annotation(ticker, "hline", "AFT_REV",
                             label=f"AFT {arrow}  {sig.confidence:.0%}",
                             ts=ts_str, price=lvl, direction=sig.direction)

    if _last_close:
        sig_color = "#22c55e" if sig.direction == "bullish" else "#ef4444"
        emit_annotation(
            ticker, "marker", sig.strategy_id,
            label=f"{sig.strategy_id} {arrow}  {sig.confidence:.0%}",
            ts=ts_str, price=_last_close,
            direction=sig.direction, color=sig_color,
        )
