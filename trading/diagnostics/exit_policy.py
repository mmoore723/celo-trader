"""Read-only descriptions of the policy actually selected by the manager."""
from __future__ import annotations

import pandas as pd
import json

from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
from trading.v2_orb_paper_exit import V2_EXIT_MINUTES_BY_STRATEGY
from trading.vwap_displacement_exit import (
    FALLBACK_HOLD_MINUTES, VWAP_DISPLACEMENT_STRATEGY_ID,
)


def reviewed_exit_description(trade: dict, position: dict, now: object) -> str | None:
    """Narrate reviewed exits without evaluating, changing or placing an order.

    Return None for the existing generic manager. Use the same strategy
    classification and timer catalog as the actual exit dispatcher.
    """
    from trading.trend_profit_exit import replacement_policy, policy_label
    policy = replacement_policy(trade)
    if policy:
        return policy_label(policy)+'. Account safety and session close remain active. No separate initial loss stop is added.'
    strategy = str(trade.get("strategy_id") or "").strip().upper()
    if not uses_v2_orb_execution_profile(strategy):
        return None
    pending = str(position.get("exit_pending_reason") or "").strip()
    if pending:
        return f"Exit requested: {pending}. Waiting for the broker to confirm the close."
    from config.research_order_specs import SPECS
    if strategy in SPECS:
        try:
            raw = trade.get('strategy_context_json') or {}
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw)
            spec = SPECS[strategy]
            if meta.get('strategy_version') != spec.version or meta.get('research_order_route') != 'exact_research_v1':
                raise ValueError('Unverified execution context')
            selected = meta.get('selected_test_policy')
            if selected is not None:
                from config.research_pair_policy import validate
                selected = validate(selected, strategy, trade.get('ticker'), spec.version)
                if selected['exit_minutes'] is not None:
                    return (
                        f"Strategy exit: selected {selected['exit_minutes']}-minute timer. "
                        "No strategy-level initial loss stop or profit trail is active in this timer policy. "
                        "Calculated support, option stops and targets are references only, not exit triggers. "
                        "Account safety and session-close exits still apply."
                    )
            if strategy in ('RESEARCH_QQQ_TREND_V2', 'RESEARCH_FAILED_RANGE_V2'):
                return ("Strategy exit: 30-minute timer. No strategy-level initial loss stop or profit trail is active. "
                        "Calculated stop and target levels are references only. Account safety and session-close exits still apply.")
            from strategy_health.exit_protocols import PROTOCOLS
            from strategy_health import gap_fill_exit
            protocol = meta.get('authored_exit_protocol')
            if strategy != 'RESEARCH_CTX_ORB_ATR10_V2' and protocol != PROTOCOLS.get(spec.source):
                if not (strategy == gap_fill_exit.STRATEGY_ID and protocol == gap_fill_exit.PROTOCOL):
                    raise ValueError('Unverified exit protocol')
            if strategy == 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK':
                return (f"Strategy exit: underlying stop {meta.get('underlying_stop', 'unavailable')} and "
                        f"target {meta.get('underlying_target', 'unavailable')}, checked on completed 5-minute bars. "
                        "The entry bar is skipped; the 24-bar cap is 125 minutes from the signal bar start. "
                        "No separate profit-giveback trail is active. Account safety and session-close exits still apply.")
            return (f"Strategy exit: the trade's frozen chart-based rules ({protocol or spec.source}). "
                    "Generic option-premium stops and generic staged targets do not control this trade. "
                    "Recorded reference prices are not confirmed protection unless used by those rules. "
                    "Account safety and session-close exits still apply.")
        except (ValueError, TypeError, KeyError):
            return ("Exit policy could not be verified from this trade's saved settings. "
                    "Do not treat displayed reference levels as active stops. The execution safety checks remain unchanged.")
    if strategy == VWAP_DISPLACEMENT_STRATEGY_ID:
        return (
            "Strategy exit: prior-high target or a completed 5-minute close below VWAP; "
            f"15:55 ET session cap. Missing structure has a {FALLBACK_HOLD_MINUTES}-minute "
            "fallback. Generic option stops and staged profit targets do not control this trade."
        )
    minutes = V2_EXIT_MINUTES_BY_STRATEGY.get(strategy)
    if minutes is None:
        return "Strategy exit policy unavailable in this display. No stop protection is confirmed here."
    raw_entry = position.get("entry_time") or trade.get("entry_time")
    try:
        entry, current = pd.Timestamp(raw_entry), pd.Timestamp(now)
        if pd.isna(entry) or pd.isna(current):
            raise ValueError("missing clock")
        entry = entry.tz_localize("America/New_York") if entry.tzinfo is None else entry
        current = current.tz_localize("America/New_York") if current.tzinfo is None else current
        elapsed = max(0.0, (current - entry).total_seconds() / 60)
        clock = (
            f"{elapsed:.1f}/{minutes} minutes held, {minutes - elapsed:.1f} minutes left."
            if elapsed < minutes else "Timer reached; close is due, not yet confirmed here."
        )
    except (TypeError, ValueError, OverflowError):
        clock = "Entry time unavailable; the manager must check its missing-time safety exit."
    profit = (
        " Profit protection: after $65 profit per contract, exit on more than 35% giveback of peak profit, "
        "checked at most once per minute using a valid fresh option bid."
        if strategy == 'V2_TSLA_TWO_LEG_TREND_PULLBACK' and str(trade.get('ticker') or '').upper() == 'TSLA'
        and trade.get('paper') in (True, False, 0, 1) else ''
    )
    return (
        f"Strategy exit: {minutes}-minute timer. {clock} "
        "Generic option stops, trails and staged profit targets do not control this trade. "
        "No strategy-level initial loss stop is active. Account-level safety controls remain separate."
        + profit
    )


def entry_protection_summary(trade: dict, now: object, reference_stop: float, reference_target: float) -> dict:
    """Shared entry/log/AI description. Never mutates state or evaluates an order."""
    try:
        description = reviewed_exit_description(trade, {}, now)
        from config.strategy_catalog import REVIEWED_STRATEGIES
        if description is None and str(trade.get('strategy_id') or '').strip().upper() in REVIEWED_STRATEGIES:
            description = 'Exit policy verification unavailable. Calculated reference levels are not confirmed active protection.'
    except Exception:
        # A display failure after a confirmed fill must not interrupt bookkeeping.
        description = 'Exit description unavailable. Active protection is not confirmed by this display.'
    # Entry-time reference calculations are not proof of current monitoring,
    # even on the generic route. The manager publishes actual enforcement.
    reviewed = True
    from risk.protection import classify_risk_levels
    inventory = classify_risk_levels(dict(trade, stop_price=reference_stop, target_price=reference_target))
    return {
        'risk_classification': inventory,
        'description': description or 'Generic risk manager; prices below are its initial calculated references, not guaranteed fills.',
        'generic_reference_levels_only': reviewed,
        'stop_price': None if reviewed else reference_stop,
        'target_price': None if reviewed else reference_target,
        'reference_stop_price': reference_stop,
        'reference_target_price': reference_target,
    }
