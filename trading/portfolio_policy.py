"""Reviewed portfolio-level scheduling rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Mapping, Optional


@dataclass(frozen=True)
class PortfolioPolicyDecision:
    allowed: bool
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None


SPY_AFTERNOON_RESERVATION_START = time(13, 45)
SPY_AFTERNOON_RESERVATION_END = time(15, 0)
SPY_TREND_MIN_ROOM_ATR = 0.50


def reviewed_strategy_entry_policy(
    *,
    ticker: object,
    strategy_id: object,
    direction: object,
    signal_meta: Mapping[str, object],
) -> PortfolioPolicyDecision:
    """Apply only entry-context rules supported by chronological quote evidence.

    The Trend Continuation observer still records every raw candidate.  This
    policy only controls whether an already-observed SPY candidate may reach
    an order, keeping research collection separate from trade authorization.
    """
    if (
        str(ticker or "").strip().upper() != "SPY"
        or str(strategy_id or "").strip().upper() != "V2_SPY_TREND_CONT"
    ):
        return PortfolioPolicyDecision(allowed=True)

    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction in {"bullish", "long"}:
        level_name = "resistance"
        raw_distance = signal_meta.get("pa_resistance_distance_atr")
    elif normalized_direction in {"bearish", "short"}:
        level_name = "support"
        raw_distance = signal_meta.get("pa_support_distance_atr")
    else:
        return PortfolioPolicyDecision(allowed=True)

    # The predeclared research rule treats no detected opposing pivot as open
    # space. Preserve that exact behavior rather than inventing a substitute.
    if raw_distance is None:
        return PortfolioPolicyDecision(allowed=True)
    try:
        distance = float(raw_distance)
    except (TypeError, ValueError):
        return PortfolioPolicyDecision(allowed=True)
    if distance >= SPY_TREND_MIN_ROOM_ATR:
        return PortfolioPolicyDecision(allowed=True)

    return PortfolioPolicyDecision(
        allowed=False,
        reason_code="spy_trend_level_too_close",
        reason_detail=(
            f"The next {level_name} level was only {distance:.2f} ATR away. "
            f"SPY Trend requires at least {SPY_TREND_MIN_ROOM_ATR:.2f} ATR "
            "of open space before it can place an order."
        ),
    )


def reviewed_portfolio_entry_policy(
    *,
    ticker: object,
    strategy_id: object,
    now_et: datetime,
    settings: Mapping[str, object],
) -> PortfolioPolicyDecision:
    """Coordinate reviewed strategies that compete for one SPY position slot.

    Chronological paid-quote research selected a 13:45 ET cutoff for new SPY
    Trend Continuation entries. The reservation applies only while the
    reviewed SPY Afternoon FVG strategy is enabled and only through the end of
    that strategy's 15:00 ET entry window. It is not a daily trade limit.
    """
    clock_time = now_et.timetz().replace(tzinfo=None)
    if (
        str(ticker or "").strip().upper() == "SPY"
        and str(strategy_id or "").strip().upper() == "V2_SPY_TREND_CONT"
        and bool(settings.get("strategy_spy_afternoon_fvg_v2_enabled", False))
        and SPY_AFTERNOON_RESERVATION_START <= clock_time <= SPY_AFTERNOON_RESERVATION_END
    ):
        return PortfolioPolicyDecision(
            allowed=False,
            reason_code="spy_afternoon_fvg_slot_reserved",
            reason_detail=(
                "A reviewed SPY Trend Continuation setup arrived between "
                "1:45 and 3:00 PM ET. The bot kept the SPY position slot free "
                "for the reviewed Afternoon FVG setup during its validated window."
            ),
        )
    return PortfolioPolicyDecision(allowed=True)
