"""Longer-expiration research selection; no orders or primary-PF writes.

This selector is not connected to the worker until its separate exit ledger and
comparison summaries are implemented. A selection alone is not a research result.
"""
from datetime import date, timedelta
from inspect import getattr_static
import math
import re

from strategy_health.impulse_exit import et, executable_bid

PROFILE = 'expiration_8_21_nearest_v1'
MIN_DTE, MAX_DTE = 8, 21
MIN_ASK, MAX_ASK = 1.50, 10.00
MAX_SPREAD_PCT = .08
MAX_ENTRY_DELAY_SECONDS = 60


def identity_matches(symbol, *, ticker, expiry, direction, strike):
    """Require the contract's encoded identity to match the requested chain.

    Root aliases/adjusted deliverables are not guessed. Unknown identities stay
    rejected rather than being modeled as an ordinary 100-share contract.
    """
    match = re.fullmatch(r'(.+?)(\d{6})([CP])(\d{8})', str(symbol or ''))
    if not match:
        return False
    root, expiration, side, encoded_strike = match.groups()
    try:
        return (root == ticker and expiration == date.fromisoformat(expiry).strftime('%y%m%d')
                and side == ('C' if direction == 'bullish' else 'P')
                and math.isclose(int(encoded_strike)/1000, float(strike), rel_tol=0, abs_tol=1e-8))
    except (TypeError, ValueError, OverflowError):
        return False


def _valid_price(bid, ask):
    return (all(math.isfinite(v) for v in (bid, ask)) and 0 < bid <= ask
            and MIN_ASK <= ask <= MAX_ASK
            and (ask-bid)/((ask+bid)/2) <= MAX_SPREAD_PCT)


def select(readers, *, ticker, direction, underlying_price, setup_at, clock):
    """Read at most one listing, one nearest-expiry chain, one selected quote.

    Never fall through to a later expiry or second contract after the selected
    quote fails. Never reuse today's data to reprice an expired setup. Quote
    refresh may invalidate a chain selection but cannot expand its price rules.
    """
    setup, started = et(setup_at), et(clock())
    info = dict(profile_version=PROFILE, status='not_selected', reason=None,
                setup_at=setup.isoformat(), selection_started_at=started.isoformat(),
                minimum_dte=MIN_DTE, maximum_dte=MAX_DTE,
                minimum_ask=MIN_ASK, maximum_ask=MAX_ASK,
                maximum_spread_pct=MAX_SPREAD_PCT,
                reads=dict(expirations=0, chain=0, quote=0), contract=None)

    def finish(reason):
        info['reason'] = reason
        info['selection_finished_at'] = et(clock()).isoformat()
        return info

    def timely():
        now = et(clock())
        return (now.date() == setup.date()
                and 0 <= (now-setup).total_seconds() <= MAX_ENTRY_DELAY_SECONDS
                and setup.replace(hour=9, minute=30, second=0, microsecond=0) <= setup
                and now < setup.replace(hour=16, minute=0, second=0, microsecond=0))

    ticker = str(ticker or '').strip().upper()
    try:
        price = float(underlying_price)
    except (ValueError, TypeError, OverflowError):
        return finish('invalid_setup')
    if not ticker or direction not in {'bullish', 'bearish'} or not math.isfinite(price) or price <= 0:
        return finish('invalid_setup')
    if not timely():
        return finish('setup_expired')
    required = ('get_research_expiration_details', 'get_research_option_chain', 'get_option_quote')
    if not all(callable(getattr_static(readers, name, None)) for name in required):
        return finish('research_reader_unavailable')
    try:
        info['reads']['expirations'] += 1
        listing = readers.get_research_expiration_details(
            ticker, minimum_dte=MIN_DTE, maximum_dte=MAX_DTE, limit=128)
    except Exception:
        return finish('expiration_lookup_failed')
    info['expiration_lookup'] = listing
    if not timely():
        return finish('setup_expired')
    if not isinstance(listing, dict) or listing.get('as_of_date') != setup.date().isoformat():
        return finish('expiration_date_mismatch')
    if listing.get('lookup_status') != 'ok':
        return finish('expiration_data_unavailable')
    try:
        dates = [date.fromisoformat(value) for value in listing.get('expirations', [])]
    except (TypeError, ValueError):
        return finish('invalid_expiration_dates')
    eligible = sorted(d for d in dates if MIN_DTE <= (d-setup.date()).days <= MAX_DTE)
    if not eligible:
        return finish('no_expirations_in_window')
    expiry = eligible[0].isoformat()
    info['expiration'] = expiry
    try:
        info['reads']['chain'] += 1
        chain = readers.get_research_option_chain(ticker, expiry, 'call' if direction == 'bullish' else 'put')
    except Exception:
        return finish('chain_lookup_failed')
    if not timely():
        return finish('setup_expired')
    candidates = []
    info['identity_rejections'] = 0
    for row in chain or []:
        try:
            bid, ask, strike = (float(row[key]) for key in ('bid', 'ask', 'strike'))
            symbol = str(row.get('symbol') or '')
            otm = strike > price if direction == 'bullish' else strike < price
            if not symbol or not math.isfinite(strike) or strike <= 0 or not otm or not _valid_price(bid, ask):
                continue
            if not identity_matches(symbol, ticker=ticker, expiry=expiry, direction=direction, strike=strike):
                info['identity_rejections'] += 1
                continue
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
        candidates.append((abs(strike-price), (ask-bid)/((ask+bid)/2), symbol, strike))
    info['eligible_contracts'] = len(candidates)
    if not candidates:
        return finish('contract_identity_mismatch' if info['identity_rejections'] else 'no_contract_in_profile')
    _, _, symbol, strike = min(candidates)
    info['selected_symbol'] = symbol
    try:
        info['reads']['quote'] += 1
        quote = readers.get_option_quote(symbol)
        received = et(clock())
    except Exception:
        return finish('quote_lookup_failed')
    if not timely():
        return finish('setup_expired')
    # Both sides must be exchange-stamped within 60 seconds of receipt. Entry
    # is at receipt (when known), not backdated to either exchange stamp.
    if not isinstance(quote, dict):
        return finish('entry_quote_unusable')
    decision = received-timedelta(seconds=60)
    bid_quote = executable_bid(quote, contract=symbol, decision_at=decision, received_at=received)
    ask_quote = executable_bid(dict(quote or {}, bid_date=(quote or {}).get('ask_date')),
                               contract=symbol, decision_at=decision, received_at=received)
    if not bid_quote or not ask_quote:
        return finish('entry_quote_unusable')
    bid, ask = float(quote['bid']), float(quote['ask'])
    if not _valid_price(bid, ask):
        return finish('refreshed_quote_outside_profile')
    info.update(status='selected', contract=dict(symbol=symbol, expiry=expiry, strike=strike,
                bid=bid, ask=ask, bid_at=bid_quote[1], ask_at=ask_quote[1],
                entry_quote_at=received.isoformat(), source='tradier', source_symbol=quote['source_symbol']))
    return finish('selected')
