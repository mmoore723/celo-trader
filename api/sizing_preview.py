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
