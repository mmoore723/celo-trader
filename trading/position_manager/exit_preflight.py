"""Retry decided full exits without depending on price or candle availability."""
import math

from database.helpers import _to_et_datetime
from trading.v2_orb_paper_exit import evaluate_v2_orb_paper_exit

TIMED_ROUTES = frozenset({
    'V2_ORB_PULLBACK', 'V2_SPY_TREND_CONT', 'V2_SPY_AFTERNOON_FVG',
    'V2_FAILED_OR_BREAK_VWAP_REVERSION',
})


def full_exit_reason(trade, state, now):
    pending = state.get('exit_pending_reason')
    if pending and not pending.startswith('stage1'):
        return pending
    if trade.get('strategy_id') in TIMED_ROUTES:
        entry = _to_et_datetime(trade['entry_time']) if trade.get('entry_time') else None
        due, reason = evaluate_v2_orb_paper_exit(entry, now, trade['strategy_id'])
        if due:
            return reason
    return None


def executable_quote(market, symbol):
    """A failed quote must not suppress an already-decided full liquidation."""
    try:
        quote = market.get_option_quote(symbol)
        bid = float((quote or {}).get('bid') or 0)
        ask = float((quote or {}).get('ask') or 0)
        if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
            return bid, quote
    except Exception:
        pass
    return None, None
