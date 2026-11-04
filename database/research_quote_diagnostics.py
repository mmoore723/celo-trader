"""Bounded, append-only quote validation evidence. Never used to price exits."""
import json
import math
from datetime import timedelta

from strategy_health.impulse_exit import et, executable_bid


def rejection(quote, contract, decision, received, deadline):
    if et(received) > et(deadline):
        return 'receipt_after_deadline'
    if not isinstance(quote, dict):
        return 'quote_unavailable'
    if quote.get('symbol') != contract or quote.get('source_symbol') != contract:
        return 'contract_mismatch'
    try:
        import pandas as pd
        stamp = quote['bid_date']
        if isinstance(stamp, (int, float)):
            stamp = pd.Timestamp(stamp, unit='ms', tz='UTC').to_pydatetime()
        stamp = et(stamp)
        if stamp < et(decision):
            return 'bid_before_decision'
        if stamp > et(received):
            return 'future_bid'
        if et(received)-stamp > timedelta(seconds=120):
            return 'stale_bid'
    except (KeyError, TypeError, ValueError, OverflowError):
        return 'invalid_bid_timestamp'
    return 'accepted' if executable_bid(quote, contract=contract, decision_at=decision,
                                        received_at=received) else 'invalid_bid_ask'


def record(conn, *, candidate_id, protocol, contract, decision, requested, received,
           deadline, quote):
    outcome = rejection(quote, contract, decision, received, deadline)
    conn.execute('''CREATE TABLE IF NOT EXISTS research_exit_quote_diagnostics (
        candidate_id TEXT NOT NULL, protocol TEXT NOT NULL, contract_symbol TEXT NOT NULL,
        decision_at TEXT NOT NULL, requested_at TEXT NOT NULL, received_at TEXT NOT NULL,
        receipt_minute TEXT NOT NULL, outcome TEXT NOT NULL, quote_json TEXT NOT NULL,
        UNIQUE(candidate_id,protocol,decision_at,receipt_minute,outcome))''')
    fields = ('symbol','source_symbol','bid','ask','bid_date','ask_date',
              'bidsize','asksize','bid_size','ask_size','source')
    values = {key: quote.get(key) for key in fields} if isinstance(quote, dict) else {}
    values = {key: (None if isinstance(value, float) and not math.isfinite(value) else value)
              for key, value in values.items()}
    conn.execute('''INSERT OR IGNORE INTO research_exit_quote_diagnostics VALUES (?,?,?,?,?,?,?,?,?)''',
                 (candidate_id, protocol, contract, et(decision).isoformat(),
                  et(requested).isoformat(), et(received).isoformat(),
                  et(received).replace(second=0,microsecond=0).isoformat(), outcome,
                  json.dumps(values, default=str, allow_nan=False)))
    return outcome
