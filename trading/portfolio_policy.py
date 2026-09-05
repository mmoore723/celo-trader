"""Reviewed portfolio-level scheduling rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal, Mapping, Optional


@dataclass(frozen=True)
class PortfolioPolicyDecision:
    allowed: bool
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None


SPY_AFTERNOON_RESERVATION_START = time(13, 45)
SPY_AFTERNOON_RESERVATION_END = time(15, 0)


def _reviewed_strategy_structure_requirement(
    *, ticker: object, strategy_id: object, direction: object,
) -> tuple[str, str] | None:
    """Return the recorded evidence field required by a reviewed entry rule."""
    if (
        str(ticker or "").strip().upper() != "SPY"
        or str(strategy_id or "").strip().upper() != "V2_SPY_TREND_CONT"
    ):
        return None
    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction in {"bullish", "long"}:
        return "pa_consecutive_higher_lows", "higher lows"
    if normalized_direction in {"bearish", "short"}:
        return "pa_consecutive_lower_highs", "lower highs"
    return None


def reviewed_strategy_entry_evidence_status(
    *,
    ticker: object,
    strategy_id: object,
    direction: object,
    signal_meta: Mapping[str, object],
) -> Literal["not_applicable", "unscored", "passed", "rejected"]:
    """Classify saved evidence against the entry rule currently in production.

    Older candidates may predate the metadata required to reconstruct a newer
    rule. They must not be silently counted as either wins or losses for the
    current version.
    """
    requirement = _reviewed_strategy_structure_requirement(
        ticker=ticker, strategy_id=strategy_id, direction=direction,
    )
    if requirement is None:
        return "not_applicable"
    required_field, _ = requirement
    if required_field not in signal_meta:
        return "unscored"
    decision = reviewed_strategy_entry_policy(
        ticker=ticker,
        strategy_id=strategy_id,
        direction=direction,
        signal_meta=signal_meta,
    )
    return "passed" if decision.allowed else "rejected"


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
    requirement = _reviewed_strategy_structure_requirement(
        ticker=ticker, strategy_id=strategy_id, direction=direction,
    )
    if requirement is None:
        return PortfolioPolicyDecision(allowed=True)
    required_field, structure_name = requirement
    structure_present = signal_meta.get(required_field) is True

    if structure_present:
        return PortfolioPolicyDecision(allowed=True)

    return PortfolioPolicyDecision(
        allowed=False,
        reason_code="spy_trend_three_bar_structure_missing",
        reason_detail=(
            f"The last three completed candles did not form {structure_name} "
            "in the trade direction."
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
