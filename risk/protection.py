"""Read-only risk inventory. Classification never activates an exit condition."""
from __future__ import annotations

import json
import math
from decimal import Decimal

ENFORCED = 'Enforced'
REFERENCE = 'Reference-only'
UNAVAILABLE = 'Unavailable'


def full_debit_risk(premium: float) -> float:
    """Long-option debit plus configured round-trip fees, not a stop-fill promise.

    Caller supplies its bounded maximum entry premium. No credit is given for
    a software stop, structural conversion, profit target or hoped-for exit bid.
    This is not an assignment/exercise risk model or a short-option risk model.
    """
    from config import COMMISSION_PER_CONTRACT
    price, fee = Decimal(str(premium)), Decimal(str(COMMISSION_PER_CONTRACT))
    if not price.is_finite() or price <= 0 or not fee.is_finite() or fee < 0:
        raise ValueError('Entry premium or configured fees unavailable')
    return float(price * 100 + fee * 2)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def classify_risk_levels(trade, *, position=None, monitored_fields=(), monitoring_reason=None):
    """Inventory levels the bot actually has, without inferring execution from value.

    monitored_fields is supplied only by the manager after choosing its actual
    execution branch. API/entry callers omit it: future monitoring is not proof
    of present enforcement. Stored classifications are not trusted as inputs.
    """
    position = position or {}
    try:
        raw = trade.get('strategy_context_json') or {}
        context = json.loads(raw) if isinstance(raw, str) else dict(raw)
        if not isinstance(context, dict):
            raise ValueError('Invalid context')
    except (ValueError, TypeError):
        context = {}
    values = {
        'option_stop': trade.get('stop_price'),
        'option_target': trade.get('target_price'),
        'underlying_stop': context.get('underlying_stop'),
        'underlying_target': context.get('underlying_target'),
        'support': context.get('pa_nearest_support'),
        'resistance': context.get('pa_nearest_resistance'),
        'or_midpoint': context.get('or_midpoint'),
        'previous_high': context.get('previous_high'),
        'sma20': context.get('sma20'),
        'struct_stop_price': position.get('struct_stop_price'),
        'atr_trail_stop': position.get('atr_trail_stop'),
        'initial_atr_stop': position.get('initial_atr_stop'),
        'stage1_be_price': position.get('stage1_be_price'),
        'simplified_trail_underlying': position.get('simplified_trail_underlying'),
        'simplified_trail_stop': position.get('simplified_trail_stop'),
    }
    # Preserve additional recorded level fields instead of quietly dropping them.
    for source in (context, position):
        for key, value in source.items():
            if key.endswith(('support', 'resistance', 'stop', 'target', 'stop_price', 'target_price')):
                if not isinstance(value, (dict, list)):
                    values.setdefault(key, value)
    monitored = set(monitored_fields)
    expected = set(monitored_risk_fields(trade, branch='reviewed'))
    from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
    policy_known = uses_v2_orb_execution_profile(trade.get('strategy_id'))
    from config.research_order_specs import SPECS
    sid = trade.get('strategy_id')
    if sid in SPECS:
        policy_known = policy_known and context.get('strategy_version') == SPECS[sid].version and context.get('research_order_route') == 'exact_research_v1'
        if context.get('selected_test_policy') is not None:
            try:
                from config.research_pair_policy import validate
                validate(context['selected_test_policy'], sid, trade.get('ticker'), SPECS[sid].version)
            except (ValueError, TypeError, KeyError):
                policy_known = False
    levels = []
    for name, raw in values.items():
        value = _number(raw)
        if value is None:
            state, reason = UNAVAILABLE, 'No valid recorded price level.'
        elif name in monitored and monitoring_reason is None:
            state, reason = ENFORCED, 'The selected execution branch monitors this level; fill price is not guaranteed.'
        elif name in monitored:
            state, reason = UNAVAILABLE, monitoring_reason
        elif name in expected:
            state, reason = UNAVAILABLE, 'Policy uses this level, but current monitoring data has not been verified.'
        elif not policy_known or (sid == 'V2_GAP_FILL_RTH' and name in ('underlying_stop', 'underlying_target')):
            state, reason = UNAVAILABLE, 'The active execution role of this recorded level cannot be verified here.'
        else:
            state, reason = REFERENCE, 'Recorded analysis level; not verified as an active exit trigger in this snapshot.'
        levels.append(dict(name=name, value=value, state=state, reason=reason,
                           price_basis='option premium' if name in {
                               'option_stop','option_target','struct_stop_price','atr_trail_stop',
                               'initial_atr_stop','stage1_be_price','simplified_trail_stop'} else 'underlying'))
    return dict(version='risk-levels-v1', levels=levels,
                identity={k: trade.get(k) for k in ('id', 'contract_symbol', 'broker_account_id', 'paper')},
                sizing_basis='Full long-option debit plus configured round-trip fees. No assumed stop-fill credit.')


def monitored_risk_fields(trade, *, branch):
    """Match explicit execution paths, not a strategy-name substring heuristic."""
    if branch == 'adaptive':
        return ('struct_stop_price', 'atr_trail_stop', 'initial_atr_stop', 'stage1_be_price')
    if branch == 'simplified':
        return ('struct_stop_price', 'initial_atr_stop', 'simplified_trail_underlying')
    if branch != 'reviewed':
        return ()
    from config.research_order_specs import SPECS
    sid = trade.get('strategy_id')
    if sid not in SPECS:
        return ('previous_high',) if sid == 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG' else ()
    try:
        from trading.research_order_exit import context
        meta = context(trade)
        spec = SPECS[sid]
        if meta.get('strategy_version') != spec.version or meta.get('research_order_route') != 'exact_research_v1':
            return ()
        if meta.get('selected_test_policy') is not None:
            from config.research_pair_policy import validate
            if validate(meta['selected_test_policy'], sid, trade.get('ticker'), spec.version)['exit_minutes'] is not None:
                return ()
        if spec.adapter in ('native_trend', 'native_fvg', 'retouch', 'two_leg'):
            return ()
        if sid in ('RESEARCH_QQQ_TREND_V2', 'RESEARCH_FAILED_RANGE_V2'):
            return ()
        if sid == 'RESEARCH_CTX_ORB_ATR10_V2' or spec.source == 'CTX_ORB_NR7_OR_INSIDE':
            return ('or_midpoint',)
        if spec.adapter == 'context':
            return ('previous_high',)
        if spec.adapter == 'squeeze':
            return ('sma20',)
        # These engines consume the frozen initial levels. Gap Fill additionally
        # evolves its own stop; a recorded initial level is not its current stop.
        if sid == 'V2_GAP_FILL_RTH':
            return ()
        from strategy_health.exit_protocols import PROTOCOLS
        if PROTOCOLS.get(spec.source) and meta.get('authored_exit_protocol') == PROTOCOLS[spec.source]:
            return ('underlying_stop', 'underlying_target')
    except (ValueError, TypeError, KeyError):
        pass
    return ()


def monitoring_failure(*, now, quote, frame, reason):
    """Conservative display health, never an execution gate or exit signal."""
    import pandas as pd
    if any(token in str(reason) for token in ('missing', 'invalid', 'waiting', 'duplicate', 'late_entry')):
        return 'Execution inputs unavailable: ' + str(reason)
    try:
        current = pd.Timestamp(now)
        received = pd.Timestamp(quote['quote_received_at'])
        age = float(quote['quote_age_seconds'])
        bid, ask = float(quote['bid']), float(quote['ask'])
        if (current.tzinfo is None or received.tzinfo is None
                or not 0 <= (current-received).total_seconds() <= 60
                or not 0 <= age <= 60 or not 0 < bid <= ask or not math.isfinite(ask)):
            raise ValueError('Stale or invalid quote')
        if frame is None or frame.empty:
            raise ValueError('No underlying bars')
        stamps = pd.to_datetime(frame['time'])
        if stamps.dt.tz is None:
            stamps = stamps.dt.tz_localize('America/New_York')
        completed = stamps[stamps + pd.Timedelta(minutes=1) <= current]
        if completed.empty or not 0 <= (current-completed.max()).total_seconds() <= 120:
            raise ValueError('No recent completed bar')
        session = completed[completed.dt.date == current.date()].sort_values()
        if session.duplicated().any() or (session.diff().dropna() > pd.Timedelta(minutes=1)).any():
            raise ValueError('Incomplete underlying bar sequence')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return 'Fresh option quote and completed underlying bars are not both verified.'
    return None


def display_risk_levels(trade, snapshot, now):
    """Expired or cross-account snapshots cannot claim current enforcement."""
    import pandas as pd
    fallback = classify_risk_levels(trade)
    try:
        if trade.get('status') == 'closed' or snapshot['identity'] != fallback['identity']:
            return fallback
        age = (pd.Timestamp(now) - pd.Timestamp(snapshot['observed_at'])).total_seconds()
        if not 0 <= age <= 60:
            raise ValueError('Stale monitoring snapshot')
        if snapshot.get('version') != 'risk-levels-v1':
            return fallback
        return snapshot
    except (ValueError, TypeError, KeyError):
        return fallback
