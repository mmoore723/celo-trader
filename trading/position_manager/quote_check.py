"""Check exit quotes at decision time, with one bounded refresh opportunity."""
from strategy_health.premium_rules import quote_validation
from trading.decision_trace import note


def refresh_exit_quote(market, trade, quote, now_fn):
    now = now_fn()
    accepted, details = quote_validation(quote, now, trade['contracts'], trade['contract_symbol'])
    note('exit_quote_validation', details)
    if accepted is None:
        # Do not weaken age or size checks. A newer observation may qualify.
        from broker.read_budget import market_read_budget
        with market_read_budget(2):
            try:
                quote = market.get_option_quote(trade['contract_symbol'])
            except Exception:
                quote = None
        now = now_fn()
        _, details = quote_validation(quote, now, trade['contracts'], trade['contract_symbol'])
        note('exit_quote_refresh', {'quote': quote, 'validation': details})
    return quote, now
