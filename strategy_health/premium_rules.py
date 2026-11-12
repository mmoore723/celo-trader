"""Shared causal profit decisions. No broker, settings or database access."""
from datetime import datetime, timezone
from decimal import Decimal
import math

VERSION = 'premium-exits-v2'
GAIN_PCTS = (2, 5, 15, 20, 25)
GIVEBACK_PCTS = (15, 20, 25)
RULES = {**{f'premium_{p}pct':f'{p}% Premium Gain' for p in GAIN_PCTS},
         **{f'giveback_{p}pct':f'{p}% Peak-Profit Giveback' for p in GIVEBACK_PCTS}}
# The five additional hypotheses are explicitly research-only.
EXECUTION_RULES = frozenset(('premium_2pct','premium_25pct','giveback_25pct'))
FEE = .65  # Per contract per side; same as existing research model.
SLIPPAGE = .01  # Per option share per side, in addition to bid/ask spread.
MAX_AGE = 10
MAX_FILL_WAIT = 30
MODELED_COST = Decimal('3.30')


def rule_specifications():
    """Persist exact numbers, not merely human-readable policy names."""
    return {rule:dict(label=label,
        gain_fraction=str(Decimal(rule.split('_')[1].removesuffix('pct'))/100) if rule.startswith('premium_') else None,
        giveback_fraction=str(giveback_fraction(rule)) if rule.startswith('giveback_') else None,
        arm_dollars_per_contract=str(giveback_arm_dollars(rule)) if rule.startswith('giveback_') else None,
        modeled_cost_dollars_per_contract=str(MODELED_COST),
        minimum_giveback_sale_net=0 if rule.startswith('giveback_') else None,
        research_only=rule not in EXECUTION_RULES)
        for rule,label in RULES.items()}


def giveback_fraction(rule):
    return Decimal(rule.split('_')[1].removesuffix('pct'))/100 if rule.startswith('giveback_') and rule in RULES else None


def giveback_arm_dollars(rule):
    fraction=giveback_fraction(rule)
    if fraction is None: raise ValueError('Not a giveback policy')
    return MODELED_COST/(1-fraction)


def giveback_bid_floor(entry):
    return Decimal(str(entry)).quantize(Decimal('0.0000000001'))+MODELED_COST/100


def clock(value):
    from zoneinfo import ZoneInfo
    t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (t.replace(tzinfo=ZoneInfo('America/New_York')) if t.tzinfo is None else t).astimezone(timezone.utc)


def valid_quote(quote, received, quantity, symbol=None):
    """Reject missing sizes, stale or future clocks, crossed markets and wrong contracts."""
    try:
        if not isinstance(quote, dict) or quantity <= 0: return None
        if symbol and quote.get('symbol') != symbol: return None
        vals = [quote.get(k) for k in ('bid', 'ask', 'bidsize', 'asksize')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vals): return None
        bid, ask, size, asksize = vals
        if not 0 < bid <= ask or size < quantity or asksize <= 0: return None
        now = clock(received)
        stamps = [datetime.fromtimestamp(float(quote[k])/1000, timezone.utc) for k in ('bid_date', 'ask_date')]
        if any(not 0 <= (now-t).total_seconds() <= MAX_AGE for t in stamps): return None
        return dict(bid=bid, ask=ask, bid_size=size, bid_at=stamps[0].isoformat(),
                    ask_at=stamps[1].isoformat(), received_at=now.isoformat())
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def advance(rule, state, *, entry, quantity, quote, received, symbol=None):
    if rule not in RULES or not math.isfinite(entry) or entry <= 0 or quantity <= 0:
        raise ValueError('Invalid premium policy inputs')
    out = dict(state)
    if out.get('signal'): return out
    q = valid_quote(quote, received, quantity, symbol)
    if not q: return out
    if out.get('last_bid_at') and clock(q['bid_at']) <= clock(out['last_bid_at']): return out
    # Weighted broker fill arithmetic can serialize 1.60 as 1.6000000000000003.
    # Remove floating noise, not a tradable price increment.
    bid = Decimal(str(q['bid'])); cost = Decimal(str(entry)).quantize(Decimal('0.0000000001'))
    # Track a per-contract peak so closing part of a position does not itself
    # look like profit giveback. Additional fills use the current average cost.
    high = max(Decimal(str(out.get('high_bid', entry))), bid)
    gain, peak = bid-cost, high-cost
    fraction=giveback_fraction(rule)
    armed = fraction is not None and peak*100*(1-fraction) >= MODELED_COST
    hit = (bid >= cost*(1+Decimal(rule.split('_')[1].removesuffix('pct'))/100)
           if fraction is None else
           armed and gain <= peak*(1-fraction) and bid>=giveback_bid_floor(entry))
    out.update(high_bid=float(high), last_bid_at=q['bid_at'], armed=armed)
    if hit: out['signal'] = dict(q, reason=rule, entry=entry, quantity=quantity)
    return out


def net(entry, bid, quantity=1, *, actual_entry=False):
    return round(((max(0, bid-SLIPPAGE)-(entry+(0 if actual_entry else SLIPPAGE)))*100-2*FEE)*quantity, 6)


def replay(rule, observations, *, entry, entry_at, end, symbol, quantity=1, actual_entry=False, native_legs=()):
    """Hypothetical next-quote exit, never a same-quote fill or peak fill."""
    state = {}; start=clock(entry_at); end=clock(end); last=start
    valid=0; seen=0; largest_gap=0.0; realized=0.0; remaining=quantity; floor_wait=False
    legs=iter(sorted(native_legs,key=lambda leg:clock(leg['at'])))
    leg=next(legs,None)
    for observation in sorted(observations, key=lambda o: clock(o['received_at'])):
        now=clock(observation['received_at'])
        if now <= start or now > end: continue
        while leg and clock(leg['at'])<=now:
            remaining-=leg['quantity']
            realized+=leg['net']
            leg=next(legs,None)
        if remaining<=0:
            return dict(status='baseline',max_gap_seconds=max(largest_gap,(now-last).total_seconds()))
        seen += 1
        q=valid_quote(observation['quote'], now, remaining, symbol)
        if not q: continue
        if clock(q['bid_at']) <= start: continue
        valid += 1; largest_gap=max(largest_gap, (now-last).total_seconds()); last=now
        signal=state.get('signal')
        if signal:
            decision=clock(signal['received_at'])
            if now>decision and clock(q['bid_at'])>=decision and clock(q['ask_at'])>=decision:
                if giveback_fraction(rule) is None and (now-decision).total_seconds() > MAX_FILL_WAIT:
                    return dict(status='missing_next_quote', signal=signal)
                if giveback_fraction(rule) is not None and Decimal(str(q['bid']))<giveback_bid_floor(entry):
                    floor_wait=True
                    continue  # Never book a giveback sale below its modeled net floor.
                return dict(status='hypothetical', signal=signal, exit=q,
                            net_pnl=realized+net(entry,q['bid'],remaining,actual_entry=actual_entry), max_gap_seconds=largest_gap,
                            usable_quotes=valid, observed_quotes=seen)
        else:
            state=advance(rule,state,entry=entry,quantity=remaining,quote=observation['quote'],received=now,symbol=symbol)
    # A fully observed unfilled price floor is a real baseline outcome, not
    # missing evidence that can be excluded to improve the candidate's score.
    return dict(status='missing_next_quote' if state.get('signal') and not floor_wait else 'baseline', signal=state.get('signal'),
                unfilled_giveback_floor=floor_wait,
                max_gap_seconds=max(largest_gap,(end-last).total_seconds()),usable_quotes=valid,observed_quotes=seen)
