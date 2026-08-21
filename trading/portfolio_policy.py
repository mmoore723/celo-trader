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
