from __future__ import annotations

from datetime import datetime
import json

import pandas as pd

from strategy_health.trend_exit import first_exit
from strategy_health.impulse_exit import et


STRATEGY_ID = "V2_TREND_CONT"


def uses_tested_session_close(trade: dict) -> bool:
    from trading.research_order_exit import uses_session_close
    if uses_session_close(trade):
        return True
    if trade.get("strategy_id") != STRATEGY_ID or trade.get("ticker") not in {"SPY", "QQQ"}:
        return False
    try:
        context = trade.get("strategy_context_json") or "{}"
        context = json.loads(context) if isinstance(context, str) else dict(context)
        return (context.get("strategy_version") == "research.1"
                and context.get("authored_exit_protocol") == "trend_cont_structural_2r_75bars_completed5m_v1")
    except (TypeError, ValueError):
        return False


def evaluate_exit(
    trade: dict,
    entry_time: datetime | str | None,
    now: datetime,
    one_minute_bars: pd.DataFrame | None,
) -> tuple[bool, str]:
    if entry_time is None or one_minute_bars is None or one_minute_bars.empty:
        return True, "trend_cont_missing_exit_input_safety"
    try:
        context = trade.get("strategy_context_json") or "{}"
        context = json.loads(context) if isinstance(context, str) else dict(context)
        logical_entry = context.get("trigger_bar") or entry_time
        decision = first_exit(
            one_minute_bars,
            seed=context.get("authored_exit_state"),
            entry_at=logical_entry,
            entry_quote_at=entry_time,
            direction=str(context.get("direction") or trade.get("direction") or "").lower(),
            stop=context["underlying_stop"],
            target=context["underlying_target"],
            now=now,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return True, "trend_cont_invalid_exit_state_safety"
    if decision is None:
        return False, "hold"
    decision_at, reason = decision
    if decision_at > et(now):
        return False, "hold"
    return True, f"trend_cont_{reason}"
