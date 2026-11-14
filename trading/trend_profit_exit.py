"""Approved paper Trend Continuation partial profit and runner management."""
from decimal import Decimal
from strategy_health.premium_rules import valid_quote, clock, giveback_bid_floor

RULE = 'trend_partial_profit'
PARTIAL = 'stage1_trend_profit'
RUNNER = 'trend_profit_giveback'
REASONS = (PARTIAL, RUNNER)
PAIRS = {('V2_SPY_TREND_CONT', 'SPY'), ('RESEARCH_QQQ_TREND_V2', 'QQQ'),
         ('V2_ORB_PULLBACK', 'TSLA'), ('V2_TSLA_TWO_LEG_TREND_PULLBACK', 'TSLA'),
         ('V2_SPY_AFTERNOON_FVG', 'SPY')}


def sold_quantity(conn, trade):
    row = conn.execute("SELECT COALESCE(SUM(contracts),0) FROM trades WHERE parent_trade_id=? "
        "AND broker_account_id IS ? AND paper=1 AND status='closed' AND exit_reason=?",
        (trade.get('parent_trade_id') or trade['id'], trade.get('broker_account_id'), PARTIAL+'_profit_take')).fetchone()
    return int(row[0])


def partial_remaining(trade):
    from database import get_conn
    with get_conn() as conn:
        sold = sold_quantity(conn, trade)
        row = conn.execute("SELECT contracts FROM trades WHERE id=? AND status='open' AND paper=1 AND broker_account_id IS ?",
                           (trade['id'], trade.get('broker_account_id'))).fetchone()
        return max(0, (int(row[0])+sold)//2-sold) if row else 0


def advance(state, *, entry, quantity, sold, quote, now, symbol, gain_pct=25, giveback_pct=25):
    """Use confirmed child fills, not attempted orders, to complete stage one."""
    gain = Decimal(str(gain_pct))/100
    keep = 1-Decimal(str(giveback_pct))/100
    if gain <= 0 or not 0 < keep < 1:
        raise ValueError("Invalid profit policy thresholds")
    out = dict(state)
    original = quantity+sold
    target = original//2
    out.update(original_quantity=original, partial_target=target, partial_filled=sold)
    if sold >= target:
        out.pop('partial_signal', None)
    q = valid_quote(quote, now, quantity, symbol)
    if q and (not out.get('last_bid_at') or clock(q['bid_at']) > clock(out['last_bid_at'])):
        cost = Decimal(str(entry)).quantize(Decimal('0.0000000001'))
        bid = Decimal(str(q['bid']))
        high = max(Decimal(str(out.get('high_bid', entry))), bid)
        out.update(high_bid=float(high), last_bid_at=q['bid_at'])
        activated = high >= cost*(1+gain)
        out['activated'] = bool(out.get('activated') or activated)
        if target and sold < target and bid >= cost*(1+gain):
            out.setdefault('partial_signal', dict(q, reason=PARTIAL))
        if (sold >= target and out['activated'] and
                (high-cost)*100*keep >= Decimal('3.30') and
                bid-cost <= (high-cost)*keep and bid >= giveback_bid_floor(entry)):
            out.setdefault('signal', dict(q, reason=RUNNER))
    if sold < target and out.get('partial_signal'):
        return out, (True, PARTIAL)
    if out.get('signal'):
        return out, (True, RUNNER)
    return out, (False, 'hold')


def replacement_policy(trade):
    """Only a validated, entry-frozen paper assignment can replace native exits."""
    import json
    from trading.premium_policy import fingerprint
    from strategy_health.premium_rules import VERSION
    if trade.get('paper') not in (True, 1):
        return None
    context = trade.get('strategy_context_json') or {}
    context = json.loads(context) if isinstance(context, str) else context
    policy = context.get('premium_exit_policy') or {}
    if not policy.get('replace_native_exit'):
        return None
    if (policy.get('rule') != RULE or policy.get('version') != VERSION
            or policy.get('mode') != 'paper' or not policy.get('approval_id')
            or policy.get('account') != trade.get('broker_account_id')
            or (policy.get('strategy'), policy.get('ticker')) != (trade.get('strategy_id'), trade.get('ticker'))
            or (trade.get('strategy_id'), trade.get('ticker')) not in PAIRS
            or policy.get('gain_pct') != 10 or policy.get('giveback_pct') != 10
            or policy.get('fingerprint') != fingerprint(policy)):
        raise ValueError('Invalid frozen replacement profit policy')
    from trading.adverse_candle_exit import validate
    validate(policy)
    return policy


def policy_label(policy):
    gain = policy.get('gain_pct', 25)
    giveback = policy.get('giveback_pct', 25)
    suffix = '; no 30/90-minute timer' if policy.get('replace_native_exit') else '; native exit remains active'
    if policy.get('adverse_candle_failsafe'):
        suffix += '; before +10%, sell all after 3 adverse completed 5-minute candles AND 10% option loss'
    return f'Take half at +{gain}%, then {giveback}% peak-profit giveback'+suffix
