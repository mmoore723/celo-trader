"""
trading/annotations.py — Real-time chart annotation emitter.

Writes bot-detected patterns (FVG zones, BOS levels, signal markers, veto markers)
to LIVE_STATE["chart_annotations"][ticker] so the frontend can overlay them on the
price chart as the trading day progresses.

Annotation types:
  "hline"  — horizontal price line (BOS level, TREND_CONT swing level, OR mid)
  "zone"   — shaded price band (FVG gap, IFVG inverted zone)
  "marker" — candle-pinned marker (signal fired, veto, Stage 1 hit)
"""
from __future__ import annotations

from typing import Any

_MAX_ANNOTATIONS = 100   # per-ticker — oldest dropped when exceeded

# Default hex colors keyed by "STRATEGY_direction" or just "STRATEGY"
_COLORS: dict[str, str] = {
    "FVG_bullish":    "#06b6d4",   # cyan
    "FVG_bearish":    "#f97316",   # orange
    "IFVG_bullish":   "#a855f7",   # purple
    "IFVG_bearish":   "#ec4899",   # pink
    "BOS_MSS":        "#84cc16",   # lime
    "BOS_MSS_bullish":"#84cc16",
    "BOS_MSS_bearish":"#f87171",   # red-300 (bearish BOS)
    "VWAP_PB":        "#3b82f6",   # blue
    "MID_BRK":        "#ef4444",   # red
    "INST_ORB":       "#eab308",   # gold
    "AFT_REV":        "#14b8a6",   # teal
    "TREND_CONT":     "#8b5cf6",   # violet
    "signal_bullish": "#22c55e",   # green  — entry marker
    "signal_bearish": "#ef4444",   # red    — entry marker (put)
    "veto":           "#64748b",   # slate  — vetoed
    "stage1":         "#f59e0b",   # amber  — Stage 1 hit
    "default":        "#94a3b8",
}


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
    """Append one chart annotation to LIVE_STATE for the given ticker."""
    # Late import — avoids circular dependency at module load time
    from trading.state import LIVE_STATE  # noqa: PLC0415

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

    if "chart_annotations" not in LIVE_STATE:
        LIVE_STATE["chart_annotations"] = {}

    bucket: list = LIVE_STATE["chart_annotations"].setdefault(ticker.upper(), [])
    bucket.append(ann)

    # Cap — drop oldest entries
    if len(bucket) > _MAX_ANNOTATIONS:
        LIVE_STATE["chart_annotations"][ticker.upper()] = bucket[-_MAX_ANNOTATIONS:]


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


def clear_annotations(ticker: str | None = None) -> None:
    """Remove annotations for one ticker, or all tickers if ticker is None."""
    from trading.state import LIVE_STATE  # noqa: PLC0415
    if "chart_annotations" not in LIVE_STATE:
        return
    if ticker is None:
        LIVE_STATE["chart_annotations"] = {}
    else:
        LIVE_STATE["chart_annotations"].pop(ticker.upper(), None)
