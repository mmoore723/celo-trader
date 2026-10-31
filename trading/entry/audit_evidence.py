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
        if not received <= observed_at:
            raise ValueError('invalid_time_order')
    except (ValueError, TypeError, OverflowError):
        evidence['status']='missing_or_invalid_receipt_timestamp'
        return result
    evidence.update(model_timestamp_verified=False, model_age_seconds=None)
    try:
        model=timestamp(raw.get('updated_at'))
    except (ValueError, TypeError, OverflowError):
        # Preserve the observed snapshot without guessing the provider timezone.
        model=None
    if model is not None:
        if model > received:
            evidence['status']='future_model_timestamp'
            return result
        evidence.update(model_timestamp_verified=True,
                        model_age_seconds=(observed_at-model).total_seconds())
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
    status='recorded_provider_snapshot' if model is not None else 'recorded_snapshot_unknown_model_time'
    evidence.update(status='partial' if invalid else status, missing_fields=invalid,
                    limitation='Provider snapshot observed before entry, not fill-time recalculation. Model age is unknown when the provider timestamp lacks a verified timezone; no timezone or freshness threshold is invented.')
    return result
