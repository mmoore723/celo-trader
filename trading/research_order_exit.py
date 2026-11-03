from datetime import timedelta
import json

from config.research_order_specs import SPECS
from strategy_health.impulse_exit import et, executable_bid
from strategy_health.exit_protocols import PROTOCOLS, first_exit

ATR10 = 'RESEARCH_CTX_ORB_ATR10_V2'


def context(trade):
    raw = trade.get('strategy_context_json') or {}
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def partial_remaining(trade):
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(contracts),0) FROM trades WHERE parent_trade_id=? "
            "AND broker_account_id IS ? AND status='closed' AND exit_reason LIKE 'stage1_research_atr10%'",
            (trade.get('parent_trade_id') or trade['id'], trade.get('broker_account_id')),
        ).fetchone()
    sold = int(row[0])
    original = int(trade['contracts']) + sold
    return max(0, max(1, original // 2) - sold)


def evaluate_exit(trade, entry_time, now, frame, quote=None, *, session_close=None, compression_bars_lookup=None):
    sid = trade.get('strategy_id')
    spec = SPECS[sid]
    try:
        meta = context(trade)
        if meta.get('strategy_version') != spec.version or meta.get('research_order_route') != 'exact_research_v1':
            raise ValueError('Wrong execution version')
        if entry_time is None:
            raise ValueError('Missing entry time')
        current, filled = et(now), et(entry_time)
        cap = filled.replace(hour=15, minute=55, second=0, microsecond=0)
        if session_close is not None:
            cap = min(cap, et(session_close) - timedelta(minutes=5))
        if current >= cap:
            return True, 'research_session_close'
        selected = meta.get('selected_test_policy')
        if selected is not None:
            from config.research_pair_policy import validate
            selected = validate(selected, sid, trade.get('ticker'), spec.version)
            if selected['exit_minutes'] is not None:
                return ((True, f"selected_test_{selected['exit_minutes']}m")
                        if current >= filled + timedelta(minutes=selected['exit_minutes']) else (False, 'hold'))
        if sid == 'RESEARCH_FAILED_RANGE_V2':
            return (True, 'research_failed_range_30m') if current >= filled + timedelta(minutes=30) else (False, 'hold')
        if frame is None or frame.empty:
            return False, 'waiting_for_bars'
        logical_entry = meta.get('trigger_bar') or entry_time
        common = dict(entry_at=logical_entry, entry_quote_at=entry_time,
                      direction=meta.get('direction') or ('bearish' if trade.get('option_type') == 'put' else 'bullish'),
                      meta=meta, now=now)
        if sid == ATR10:
            from strategy_health.context_orb_exit import first_exit as midpoint_exit
            event = midpoint_exit(frame, **common, strategy_id=spec.source)
        else:
            protocol = PROTOCOLS[spec.source]
            recorded_protocol = meta.get('authored_exit_protocol')
            from strategy_health import gap_fill_exit
            legacy_gap = sid == gap_fill_exit.STRATEGY_ID and recorded_protocol == gap_fill_exit.PROTOCOL
            if recorded_protocol != protocol and not legacy_gap:
                raise ValueError('Wrong exit protocol')
            if legacy_gap:
                protocol = recorded_protocol
            event = first_exit(protocol, frame, **common, compression_bars_lookup=compression_bars_lookup)
        if event:
            stamp, reason = event
            if reason == 'waiting_for_bars' or et(stamp) > current:
                return False, 'hold'
            return True, 'research_' + reason
        if sid == ATR10 and quote:
            priced = executable_bid(quote, contract=trade['contract_symbol'],
                                    decision_at=current-timedelta(seconds=60), received_at=current)
            if priced:
                bid = priced[0]
                if bid >= float(trade['entry_price']) * 2:
                    return True, 'research_atr10_target_100'
                if bid >= float(trade['entry_price']) * 1.30 and partial_remaining(trade) > 0:
                    return True, 'stage1_research_atr10'
        return False, 'hold'
    except (KeyError, TypeError, ValueError):
        return True, 'research_invalid_exit_state_safety'


def uses_session_close(trade):
    spec = SPECS.get(trade.get('strategy_id'))
    if not spec:
        return False
    try:
        meta = context(trade)
        return meta.get('strategy_version') == spec.version and meta.get('research_order_route') == 'exact_research_v1'
    except (TypeError, ValueError):
        return False
