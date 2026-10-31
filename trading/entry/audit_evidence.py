"""Observation-only exact-contract entry evidence. No orders or extra reads."""
from datetime import datetime
import math


def timestamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result


def entry_greeks(quote, symbol, observed_at):
    quote = quote if isinstance(quote, dict) else {}
    raw = quote.get('greeks') if isinstance(quote.get('greeks'), dict) else {}
    evidence = dict(protocol='exact_contract_entry_greeks_v1', contract_symbol=symbol,
                    source_symbol=quote.get('source_symbol'), source=quote.get('quote_source'),
                    received_at=quote.get('quote_received_at'),
                    provider_updated_at=raw.get('updated_at'), observed_at=observed_at.isoformat(),
                    values={},
                    status='unavailable')
    result = dict(entry_iv=None, entry_delta=None, entry_gamma=None,
                  entry_greeks_snapshot=evidence)
    for key in ('mid_iv', 'delta', 'gamma'):
        value = raw.get(key)
        try:
            value = float(value) if value is not None and not isinstance(value, bool) else None
            if value is not None and not math.isfinite(value):
                value = None
        except (TypeError, ValueError, OverflowError):
            value = None
        evidence['values'][key] = value
    if quote.get('source_symbol') != symbol or quote.get('quote_source') != 'tradier':
        evidence['status']='unverified_contract_or_source'
        return result
    try:
        received=timestamp(quote.get('quote_received_at'))
        model=timestamp(raw.get('updated_at'))
        if not model <= received <= observed_at:
            raise ValueError('invalid_time_order')
        evidence['model_age_seconds']=(observed_at-model).total_seconds()
    except (ValueError, TypeError, OverflowError):
        evidence['status']='missing_or_invalid_model_timestamp'
        return result
    invalid=[]
    for target, key, lower, upper in [('entry_iv','mid_iv',0,float('inf')),
                                      ('entry_delta','delta',-1,1),('entry_gamma','gamma',0,float('inf'))]:
        try:
            value=raw.get(key)
            if value is None or isinstance(value,bool):
                raise ValueError('missing_numeric')
            value=float(value)
            if not math.isfinite(value) or not lower <= value <= upper or (key=='mid_iv' and value==0):
                raise ValueError('invalid_numeric')
            result[target]=value
        except (ValueError,TypeError,OverflowError):
            invalid.append(key)
    evidence.update(status='partial' if invalid else 'recorded_provider_snapshot', missing_fields=invalid,
                    limitation='Provider model snapshot, not fill-time recalculation; model age retained without an invented freshness threshold.')
    return result
