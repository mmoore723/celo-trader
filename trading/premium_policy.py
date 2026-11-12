"""Paper-only entry-frozen supplemental exit. Never submits an order."""
import json
from hashlib import sha256
from strategy_health.premium_rules import EXECUTION_RULES, VERSION, advance, clock


def scope(account, strategy, ticker, version):
    return json.dumps([account, strategy, ticker, version], separators=(',', ':'))


def fingerprint(policy):
    return sha256(json.dumps({k:v for k,v in policy.items() if k!='fingerprint'},sort_keys=True).encode()).hexdigest()


def freeze_selection(settings, strategy, ticker, version):
    # This release does not support live assignment or execution.
    if settings.get('paper_trading') is not True:
        return {}
    account=settings.get('active_broker_account_id')
    if not account or not version:
        return {}
    assignment=(settings.get('premium_exit_paper_assignments') or {}).get(scope(account,strategy,ticker,version))
    if not assignment:
        return {}
    if (assignment.get('rule') not in EXECUTION_RULES or assignment.get('version')!=VERSION
            or assignment.get('account')!=account or assignment.get('mode')!='paper'
            or assignment.get('strategy')!=strategy or assignment.get('ticker')!=ticker
            or assignment.get('strategy_version')!=version
            or assignment.get('fingerprint')!=fingerprint(assignment)
            or not assignment.get('approval_id')):
        raise ValueError('Invalid approved premium policy; entry refused')
    return {'premium_exit_policy':json.loads(json.dumps(assignment))}


def evaluate(conn, trade, quote, now, *, native_exit=False, native_reason='hold'):
    """Native/safety exits always win. Durable state is scoped to the open trade."""
    if native_exit:
        return True,native_reason
    if trade.get('paper') not in (True,1):
        return False,'hold'
    row=conn.execute("SELECT strategy_context_json FROM trades WHERE id=? AND status='open' AND paper=1 AND broker_account_id IS ?",
                     (trade['id'],trade.get('broker_account_id'))).fetchone()
    if row is None:
        return False,'hold'
    context=json.loads(row[0] or '{}')
    policy=context.get('premium_exit_policy')
    if not policy:
        return False,'hold'
    if (policy.get('rule') not in EXECUTION_RULES
            or policy.get('account')!=trade.get('broker_account_id') or policy.get('mode')!='paper'
            or policy.get('strategy')!=trade.get('strategy_id') or policy.get('ticker')!=trade.get('ticker')
            or policy.get('version')!=VERSION or policy.get('fingerprint')!=fingerprint(policy)):
        raise ValueError('Entry-frozen premium policy scope mismatch')
    if clock(now)<=clock(trade['entry_time']):
        return False,'hold'
    previous=context.get('premium_exit_state') or {}
    state=advance(policy['rule'],previous,entry=float(trade['entry_price']),
                  quantity=int(trade['contracts']),quote=quote,received=now,symbol=trade['contract_symbol'])
    if state!=previous:
        context['premium_exit_state']=state
        conn.execute('UPDATE trades SET strategy_context_json=? WHERE id=? AND paper=1 AND broker_account_id IS ?',
                     (json.dumps(context),trade['id'],trade.get('broker_account_id')))
    return (True,policy['rule']) if state.get('signal') else (False,'hold')


def evaluate_position(trade, quote, now):
    # Skip even a database read for every existing, unassigned position.
    if trade.get('paper') not in (True,1):
        return False,'hold'
    context=trade.get('strategy_context_json') or '{}'
    context=json.loads(context) if isinstance(context,str) else context
    if not context.get('premium_exit_policy'):
        return False,'hold'
    from database import get_conn
    with get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        return evaluate(conn,trade,quote,now)
