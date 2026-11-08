"""Capture existing raw levels without changing signal or risk calculations."""
from datetime import datetime, timedelta, timezone
import logging
import math
from zoneinfo import ZoneInfo

logger = logging.getLogger('celo_trader.research')


def entry_levels(strategy_id, candidate, bars, engine, timeframe_minutes):
    """Export the raw value already used by the two approved strategy engines.

    This is metadata only. No extra level calculation, future bars, or fallback
    to the ATR-adjusted stop. Any capture failure leaves trading unchanged.
    """
    if strategy_id not in {'V2_VWAP_PULLBACK', 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'}:
        return {}
    try:
        long = candidate.side.value == 'long'
        if not bars or candidate.timestamp != bars[-1].timestamp:
            raise ValueError('Candidate is not the newest completed bar')
        if strategy_id == 'V2_VWAP_PULLBACK':
            if len(bars) < 2:
                raise ValueError('Missing touch bar')
            source_bar = bars[-2]
            level = source_bar.low if long else source_bar.high
            basis = 'prior_touch_bar_low' if long else 'prior_touch_bar_high'
        else:
            source_bar = bars[-1]
            level = engine._pullback_extreme
            basis = 'observed_pullback_extreme_through_signal_bar'
        level = float(level)
        if not math.isfinite(level) or level <= 0:
            raise ValueError('Invalid raw level')
        stamp = source_bar.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('America/New_York'))
        return {'structural_levels': {
            'schema': 1, 'status': 'captured', 'support': level if long else None,
            'resistance': None if long else level, 'basis': basis,
            'timeframe_minutes': timeframe_minutes,
            'source_bar_at': stamp.isoformat(),
            'source_completed_at': (stamp + timedelta(minutes=timeframe_minutes)).isoformat(),
            'recorded_at': datetime.now(timezone.utc).isoformat(),
            'level_policy': 'raw_existing_level_capture_v1',
            'updates_after_entry': False,
        }}
    except Exception as exc:
        logger.warning('structural_level_capture_failed strategy=%s error=%s', strategy_id, type(exc).__name__)
        return {'structural_levels': {'schema': 1, 'status': 'missing',
                                      'reason': type(exc).__name__}}
