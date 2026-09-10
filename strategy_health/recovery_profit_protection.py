"""Completed recovery objective gates a research runner, not an order exit."""
from copy import deepcopy
from datetime import timedelta
import math

from strategy_health.impulse_exit import et


def freeze(state, meta, direction):
    out = deepcopy(state)
    try:
        target, reference = float(meta['v2_target']), float(meta['v2_entry_reference'])
        sign = {'bullish': 1, 'bearish': -1}[direction]
        if not all(math.isfinite(v) and v > 0 for v in (target, reference)) or sign*(target-reference) <= 0:
            raise ValueError('invalid recovery target')
        out.update(recovery_target=target, recovery_direction=sign, target_detected_at=None,
                   target_close_at=None)
    except (KeyError, ValueError, TypeError, OverflowError):
        out['trail'].update(status='invalid_context', reason='missing_frozen_recovery_target')
    return out


def observe_target(state, bars, *, entry_at, now):
    """Persist first known target close, rejecting gaps rather than backfilling.

    Bars start at minute open. Skip the partly held entry minute. A target
    touch in a wick or unfinished candle cannot arm the trail. The target is
    frozen at signal time, not recalculated with later session prices.
    """
    out = deepcopy(state)
    if out['trail']['status'] != 'collecting' or out.get('target_detected_at'):
        return out
    entry, now = et(entry_at), et(now)
    cap = entry+timedelta(minutes=30)
    first = entry.replace(second=0, microsecond=0)+timedelta(minutes=1)
    rows = {}
    try:
        for bar in bars:
            stamp = et(bar['time'])
            if not first <= stamp or stamp+timedelta(minutes=1) > min(now, cap):
                continue
            if stamp.second or stamp.microsecond or stamp in rows:
                raise ValueError('duplicate or misaligned minute')
            rows[stamp] = bar
        stamp = first
        while stamp+timedelta(minutes=1) <= min(now, cap):
            closed = stamp+timedelta(minutes=1)
            bar = rows.get(stamp)
            if bar is None:
                if now > closed+timedelta(seconds=120):
                    out['trail'].update(status='missing_path', reason='missing_recovery_candle')
                return out
            o, h, low, close = [float(bar[k]) for k in ('open','high','low','close')]
            if not all(math.isfinite(v) and v > 0 for v in (o,h,low,close)) or not low <= min(o,close) <= max(o,close) <= h:
                raise ValueError('invalid candle')
            if out['recovery_direction']*(close-out['recovery_target']) >= 0:
                if now > closed+timedelta(seconds=120):
                    out['trail'].update(status='missing_path', reason='late_recovery_candle')
                else:
                    out.update(target_close_at=closed.isoformat(), target_detected_at=now.isoformat())
                return out
            stamp = closed
    except (KeyError, ValueError, TypeError, OverflowError):
        out['trail'].update(status='missing_path', reason='invalid_recovery_candle')
    return out


def can_arm(state, quote, now):
    """Require an exchange bid observed strictly after target discovery."""
    if not state.get('target_detected_at'):
        return False
    from strategy_health.impulse_exit import executable_bid
    result = executable_bid(quote, contract=quote.get('symbol') if isinstance(quote,dict) else '',
                            decision_at=max(et(state['target_detected_at']),et(now)-timedelta(seconds=60)), received_at=now)
    return bool(result and et(result[1]) > et(state['target_detected_at']))
