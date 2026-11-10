"""Capture existing raw levels without changing signal or risk calculations."""
from datetime import datetime, timedelta, timezone
import logging
import math
from zoneinfo import ZoneInfo

logger = logging.getLogger('celo_trader.research')

# Existing candidate features, not calculated replacement stops.
RAW_LEVEL_FIELDS = {
    'V2_AFTERNOON_COMPRESSION_BREAKOUT': ('compression_low', 'compression_high'),
    'V2_AFTERNOON_REVERSAL': ('morning_low', 'morning_high'),
    'V2_SPY_ORB_RSI_MACD_SHORT': (None, 'or_high'),
}


def entry_levels(strategy_id, candidate, bars, engine, timeframe_minutes):
    """Export raw values already used by the supported strategy engines.

    This is metadata only. No extra level calculation, future bars, or fallback
    to the ATR-adjusted stop. Any capture failure leaves trading unchanged.
    """
    if strategy_id not in {'V2_VWAP_PULLBACK', 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK'} | RAW_LEVEL_FIELDS.keys():
        return {}
    try:
        long = candidate.side.value == 'long'
        if not bars or candidate.timestamp != bars[-1].timestamp:
            raise ValueError('Candidate is not the newest completed bar')
        source_field = None
        if strategy_id in RAW_LEVEL_FIELDS:
            source_field = RAW_LEVEL_FIELDS[strategy_id][0 if long else 1]
            if source_field is None:
                raise ValueError('No defined raw level for this side')
            level = candidate.features.get(source_field)
            source_bar = bars[-1]
            basis = 'existing_candidate_feature_as_of_completed_signal_bar'
        elif strategy_id == 'V2_VWAP_PULLBACK':
            if len(bars) < 2:
                raise ValueError('Missing touch bar')
            source_bar = bars[-2]
            level = source_bar.low if long else source_bar.high
            basis = 'prior_touch_bar_low' if long else 'prior_touch_bar_high'
        else:
            source_bar = bars[-1]
            level = engine._pullback_extreme
            basis = 'observed_pullback_extreme_through_signal_bar'
        if isinstance(level, bool):
            raise ValueError('Invalid boolean level')
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
            'source_field': source_field,
            'updates_after_entry': False,
        }}
    except Exception as exc:
        logger.warning('structural_level_capture_failed strategy=%s error=%s', strategy_id, type(exc).__name__)
        return {'structural_levels': {'schema': 1, 'status': 'missing',
                                      'reason': type(exc).__name__}}
