"""Read-only contract sizing. No order client methods or settings writes."""
import math
import re
from datetime import datetime, timezone

from config.engine_parameters import entry_cycle


def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None


def calculate(balance, quote, symbol):
    from risk.sizing import SizingMixin
    from risk.manager import RiskManager
    from risk.protection import full_debit_risk
    if not positive(balance):
        raise ValueError('The broker did not return a usable account balance.')
    quote = quote or {}
    if quote.get('source_symbol') != symbol:
        raise ValueError('The quote does not identify this exact option contract.')
    bid, ask = positive(quote.get('bid')), positive(quote.get('ask'))
    try:
        age = float(quote.get('quote_age_seconds'))
    except (TypeError, ValueError):
        age = math.inf
    if not bid or not ask or bid > ask or not 0 <= age <= 120:
        raise ValueError('A fresh, valid bid and ask are unavailable. Closed markets may return old quotes.')
    class PreviewSizer(SizingMixin):
        SLIPPAGE_PCT = RiskManager.SLIPPAGE_PCT
    sizer = PreviewSizer()
    sizer.account_balance = float(balance)
    entry = sizer.slippage_adjusted_entry(ask)
    rate = sizer.effective_risk_pct(balance)
    cap_rate = sizer.effective_notional_pct(balance, rate)
    debit = full_debit_risk(entry)
    quantity = sizer.calculate_contracts(entry, balance)
    budget, cap = balance * rate, balance * cap_rate
    risk_count, cost_count = int(budget / debit), int(cap / (entry * 100))
    return dict(balance=balance, bid=bid, ask=ask, maximum_entry=entry,
                fees_per_contract=round(debit-entry*100, 6), risk_budget=budget,
                purchase_cap=cap, risk_contracts=risk_count, cost_contracts=cost_count,
                contracts=quantity, total_with_fees=round(quantity*debit, 2),
                limiting='Both limits' if risk_count == cost_count else 'Risk budget' if risk_count < cost_count else 'Purchase-cost cap',
                quote_age_seconds=age, quote_received_at=quote.get('quote_received_at'),
                bid_date=quote.get('bid_date'), ask_date=quote.get('ask_date'), source=quote.get('quote_source'))


@entry_cycle
def preview(strategy_id, ticker, version, symbol, expected_scope):
    from config import get_settings, get_api_keys
    from config.engine_parameters import describe, scope_key, select_sizing
    from broker import get_clients, required_broker_credentials
    settings = get_settings()
    describe(settings, strategy_id, ticker, version)
    if not settings.get('active_broker_account_id') or scope_key(settings, strategy_id, ticker, version) != expected_scope:
        raise ValueError('Account or mode changed. Reload Settings before previewing.')
    match = re.fullmatch(r'([A-Z][A-Z0-9.]{0,9})(\d{6})[CP]\d{8}', symbol)
    if not match or match.group(1) != ticker.upper():
        raise ValueError('Enter the exact option contract symbol for this ticker, including expiration, call or put, and strike.')
    expiry = datetime.strptime(match.group(2), '%y%m%d').date()
    if expiry < datetime.now(timezone.utc).date():
        raise ValueError('This option contract has expired.')
    keys = get_api_keys()
    if any(not keys.get(key) for key, _ in required_broker_credentials(keys)):
        raise ValueError('Connect this account and its market data before previewing. No example balance is substituted.')
    broker, market = get_clients()
    account = broker.get_account()
    balance = positive(account.get('equity'))
    quote = market.get_option_quote(symbol)
    effective = select_sizing(settings, strategy_id, ticker)
    from auth.context import get_current_user_id
    from config.research_snapshot import research_settings_snapshot
    with research_settings_snapshot(get_current_user_id(), effective):
        result = calculate(balance, quote, symbol)
    # Recheck identity after remote reads so a mode/account switch cannot label old data as current.
    current = get_settings()
    if scope_key(current, strategy_id, ticker, version) != expected_scope:
        raise ValueError('Account or mode changed during the preview. Reload Settings.')
    return {**result, 'symbol':symbol, 'mode':'paper' if settings.get('paper_trading', True) else 'live',
            'as_of':datetime.now(timezone.utc).isoformat(), 'scope':expected_scope,
            'notice':'Sizing ceiling, not an order approval. Contract eligibility, buying power, signal adjustments and safety checks can reduce or block the order. Uses saved settings only.'}


def current_candidate(settings, strategy_id, ticker, version, *, now=None):
    """Read the newest exact-pair observation, never resurrect an older setup."""
    import json
    import sqlite3
    from config.paths import get_user_data_dir
    path = get_user_data_dir(create=False) / ('trades_paper.db' if settings.get('paper_trading', True) else 'trades_live.db')
    if not path.exists():
        return None, 'No setup has been recorded for this account yet.'
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM shadow_candidates WHERE broker_account_id=? AND strategy_id=? AND ticker=? ORDER BY observed_at DESC, rowid DESC LIMIT 1',
                           (settings.get('active_broker_account_id'), strategy_id, ticker.upper())).fetchone()
    if row is None:
        return None, 'The bot has no current setup for this strategy and ticker.'
    try:
        meta = json.loads(row['metadata_json'] or '{}')
        when = datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
        if when.tzinfo is None:
            return None, 'The setup timestamp is incomplete. Waiting for a new setup.'
        age = ((now or datetime.now(timezone.utc))-when).total_seconds()
        if not 0 <= age <= 120:
            return None, 'No current contract: the latest setup is more than two minutes old. Waiting for the bot.'
        if meta.get('strategy_version') != version or meta.get('observation_only'):
            return None, 'Waiting for a current trading setup for this strategy version.'
        if row['final_outcome'] != 'pending' or row['linked_trade_id'] is not None:
            return None, 'The latest setup has already been entered or stopped. Waiting for the next setup.'
        plan = meta.get('manual_plan') or {}
        contract = plan.get('contract') or {}
        source = 'Selected contract'
        if not contract.get('symbol'):
            contract = plan.get('contract_preview') or {}
            source = 'Contract being evaluated'
            if contract.get('status') != 'selected':
                return None, 'The bot is checking the setup but has not found an option contract yet.'
        symbol = contract.get('symbol')
        if not isinstance(symbol,str) or not symbol:
            return None, 'The bot has not selected an option contract yet.'
        return {'candidate_id':row['candidate_id'],'symbol':symbol,'observed_at':row['observed_at'], 'selection_stage':source}, None
    except (ValueError, TypeError, AttributeError, KeyError):
        return None, 'The setup record is incomplete. Waiting for a new setup.'


def automatic_preview(strategy_id, ticker, version, expected_scope):
    from config import get_settings
    from config.engine_parameters import describe, scope_key
    settings = get_settings()
    describe(settings,strategy_id,ticker,version)
    if not settings.get('active_broker_account_id') or scope_key(settings,strategy_id,ticker,version) != expected_scope:
        raise ValueError('Account or mode changed. Reload Settings before previewing.')
    candidate, reason = current_candidate(settings,strategy_id,ticker,version)
    if not candidate:
        return {'status':'waiting','reason':reason}
    result = preview(strategy_id,ticker,version,candidate['symbol'],expected_scope)
    latest, reason = current_candidate(get_settings(),strategy_id,ticker,version)
    if latest != candidate:
        return {'status':'waiting','reason':'The bot moved on from this contract. Refreshing the next setup.'}
    return {**result,**candidate,'status':'ready'}
