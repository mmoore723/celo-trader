"""Approved paper Trend Continuation partial profit and runner management."""
from decimal import Decimal
from strategy_health.premium_rules import valid_quote, clock, giveback_bid_floor

RULE = 'trend_partial_profit'
PARTIAL = 'stage1_trend_profit'
RUNNER = 'trend_profit_giveback'
REASONS = (PARTIAL, RUNNER)
PAIRS = {('V2_SPY_TREND_CONT', 'SPY'), ('RESEARCH_QQQ_TREND_V2', 'QQQ')}


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


def advance(state, *, entry, quantity, sold, quote, now, symbol):
    """Use confirmed child fills, not attempted orders, to complete stage one."""
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
        activated = high >= cost*Decimal('1.25')
        out['activated'] = bool(out.get('activated') or activated)
        if target and sold < target and bid >= cost*Decimal('1.25'):
            out.setdefault('partial_signal', dict(q, reason=PARTIAL))
        if (sold >= target and out['activated'] and
                (high-cost)*100*Decimal('.75') >= Decimal('3.30') and
                bid-cost <= (high-cost)*Decimal('.75') and bid >= giveback_bid_floor(entry)):
            out.setdefault('signal', dict(q, reason=RUNNER))
    if sold < target and out.get('partial_signal'):
        return out, (True, PARTIAL)
    if out.get('signal'):
        return out, (True, RUNNER)
    return out, (False, 'hold')
