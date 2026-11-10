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

# Verified signal timestamp conventions. Offset converts bar-open timestamps to
# availability; ORB retouch uses the completed breakout, not the live retouch bar.
ROUTER_LEVEL_RULES = {
    'V2_ORB_PULLBACK': ('or_low', None, 1, 'completed_1m_breakout_then_live_quote_first_retouch', 'breakout_time', 1),
    'V2_SPY_TREND_CONT': ('pa_nearest_support', 'pa_nearest_resistance', 5, 'completed_5m_signal_then_next_1m_entry', 'trigger_bar', 5),
    'V2_SPY_AFTERNOON_FVG': ('pa_nearest_support', 'pa_nearest_resistance', 5, 'completed_5m_signal_then_next_1m_entry', 'trigger_bar', 5),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('pa_nearest_support', 'pa_nearest_resistance', 1, 'completed_1m_failure_then_next_1m_entry', 'trigger_bar', 1),
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('pullback_low', 'pullback_high', 1, 'completed_1m_reclaim_then_next_1m_option_ask', 'trigger_bar', 1),
    'RESEARCH_QQQ_TREND_V2': ('pa_nearest_support', 'pa_nearest_resistance', 5, 'completed_5m_signal_then_next_1m_entry', 'trigger_bar', 5),
    'RESEARCH_CTX_ORB_ATR10_V2': ('or_low', None, 1, 'completed_1m_breakout_then_next_quote', 'trigger_bar', 0),
}
LEVEL_FIELDS = {**RAW_LEVEL_FIELDS, **{key: value[:2] for key, value in ROUTER_LEVEL_RULES.items()}}


def router_entry_levels(signal, observed_at):
    """Stamp existing signal levels before their original candidate is saved.

    No calculations of levels, execution calls, or historical repairs. Unknown
    timestamp conventions are missing evidence, never guessed.
    """
    strategy = getattr(signal, 'strategy_id', '')
    rule = ROUTER_LEVEL_RULES.get(strategy)
    meta = getattr(signal, 'meta', None)
    if rule is None or not isinstance(meta, dict) or 'structural_levels' in meta:
        return {}
    try:
        support, resistance, timeframe, timing, stamp_field, offset = rule
        if meta.get('entry_timing') != timing:
            raise ValueError('unverified_signal_timestamp_convention')
        direction = getattr(signal, 'direction', '')
        if direction not in ('bullish', 'bearish'):
            raise ValueError('missing_signal_direction')
        field = support if direction == 'bullish' else resistance
        if field is None:
            raise ValueError('undefined_level_for_side')
        value = meta.get(field)
        if isinstance(value, bool):
            raise ValueError('invalid_level')
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('invalid_level')
        raw = getattr(signal, 'trigger_bar', None) if stamp_field == 'trigger_bar' else meta.get(stamp_field)
        stamp = datetime.fromisoformat(str(raw))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('America/New_York'))
        completed = stamp + timedelta(minutes=offset)
        if observed_at.tzinfo is None or completed > observed_at:
            raise ValueError('source_not_completed_at_observation')
        return {'structural_levels': dict(schema=1, status='captured',
            support=value if direction == 'bullish' else None,
            resistance=value if direction == 'bearish' else None,
            source_field=field, basis='existing_signal_feature_at_verified_completion_horizon',
            timeframe_minutes=timeframe, source_timestamp_field=stamp_field,
            source_completed_at=completed.isoformat(), recorded_at=observed_at.isoformat(),
            level_policy='raw_router_level_capture_v1', updates_after_entry=False)}
    except Exception as exc:
        return {'structural_levels': dict(schema=1, status='missing',
            reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)}


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
