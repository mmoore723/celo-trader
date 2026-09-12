"""Final account-capacity check before a new order, never for exits/research."""
import math
import time
from decimal import Decimal, ROUND_FLOOR


def available_entry_quantity(*, account, positions, orders, symbol,
                             requested_quantity, limit_price, max_positions,
                             commission_per_contract=.65):
    """Count all broker exposure; use options BP, not leveraged stock BP.

    Broker buying power already accounts for working-order reservations; do
    not subtract them twice. Snapshots are not an atomic reservation: the
    broker remains the final authority if another client trades concurrently.
    """
    if not isinstance(account, dict) or not isinstance(positions, list) or not isinstance(orders, list):
        raise ValueError('Account capacity snapshot unavailable')
    if not symbol or not isinstance(requested_quantity, int) or requested_quantity < 1:
        raise ValueError('Invalid entry quantity or symbol')
    if not isinstance(max_positions, int) or not 1 <= max_positions <= 5:
        raise ValueError('Invalid position limit')
    equity = float(account['equity'])
    cash = float(account['cash'])
    options_bp = float(account['options_buying_power'])
    price, fee = float(limit_price), float(commission_per_contract)
    if not all(math.isfinite(x) for x in [equity, cash, options_bp, price, fee]) or price <= 0 or fee < 0:
        raise ValueError('Invalid account capacity values')
    if account.get('trading_blocked') or account.get('account_blocked'):
        return 0, 'broker_account_blocked'
    if min(equity, cash, options_bp) <= 0:
        return 0, 'options_buying_power'
    occupied = set()
    for row in positions:
        qty = float(row.get('qty', row.get('quantity')))
        if not math.isfinite(qty):
            raise ValueError('Invalid position quantity')
        if qty:
            key = row.get('option_symbol') or row.get('symbol')
            if not key:
                raise ValueError('Position symbol missing')
            occupied.add(key)
    for row in orders:
        side = str(row.get('side', '')).lower()
        key = row.get('option_symbol') or row.get('symbol')
        if not key or side not in {'buy', 'buy_to_open', 'buy_to_close', 'buy_to_cover',
                                    'sell', 'sell_to_open', 'sell_to_close', 'sell_short'}:
            raise ValueError('Working order identity unavailable')
        # Even a sell can be opening exposure; conservatively reserve its slot
        # until the broker confirms it no longer exists. No cancellation here.
        occupied.add(key)
    if symbol in occupied:
        return 0, 'contract_already_open_or_pending'
    if len(occupied) >= max_positions:
        return 0, 'account_position_limit'
    cost = Decimal(str(price)) * 100 + Decimal(str(fee))
    budget = Decimal(str(min(cash, options_bp)))
    affordable = int((budget / cost).to_integral_value(rounding=ROUND_FLOOR))
    qty = min(requested_quantity, affordable)
    return (qty, None) if qty else (0, 'options_buying_power')


def check_broker_entry_capacity(broker, risk, *, symbol, strategy_id,
                                requested_quantity, limit_price, max_positions,
                                commission_per_contract=.65):
    """Refresh broker snapshots immediately before submitting an entry."""
    started = time.monotonic()
    positions = broker.get_positions()
    orders = broker.get_open_orders()
    account = broker.get_account()
    if time.monotonic() - started > 15:
        raise ValueError('Account capacity refresh took too long; re-evaluate next cycle')
    qty, reason = available_entry_quantity(
        account=account, positions=positions, orders=orders, symbol=symbol,
        requested_quantity=requested_quantity, limit_price=limit_price,
        max_positions=max_positions, commission_per_contract=commission_per_contract)
    if not qty:
        return qty, reason
    qty = min(qty, risk.calculate_contracts(limit_price, float(account['equity']), strategy_id=strategy_id))
    return (qty, None) if qty else (0, 'fresh_equity_risk_budget')
