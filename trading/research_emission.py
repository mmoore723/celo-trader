"""Remove daily emission latches only in the order-free research replay.

Every eligible completed bar may be observed. Structural rearm rules, price
conditions, time windows, and same-bar deduplication are not daily quotas.
Never call this helper from an order evaluator or mutate a shared instance.
"""
POLICY = 'all_eligible_completed_bars_v1'
DAILY_LATCHES = {
    'V2_AFTERNOON_COMPRESSION_BREAKOUT': ('_emitted_day', None),
    'V2_MIDDAY_BREAKDOWN': ('_emitted_day', None),
    'V2_ORB_CONFIRMED_BREAKOUT': ('_emitted_day', None),
    'V2_OPENING_MOMENTUM_RTH_EXPLORATORY': ('_emitted_day', None),
    'V2_VWAP_REVERSION_RTH': ('_emitted_day', None),
    'V2_SPY_ORB_RSI_MACD_SHORT': ('_emitted_day', None),
    'V2_GAP_FILL_RTH': ('_reclaim_emitted', False),
    'V2_IMPULSE_ANCHORED_VWAP_PULLBACK': ('_fired', False),
}
# Opening Momentum already has exactly one eligible bar per session; removing
# its redundant latch does not change its signal population or evidence version.
EXPANDED_IDS = frozenset(DAILY_LATCHES) - {'V2_OPENING_MOMENTUM_RTH_EXPLORATORY'}


def prepare_bar(strategy_id, strategy):
    latch = DAILY_LATCHES.get(strategy_id)
    if latch is None:
        return
    field, empty = latch
    if not hasattr(strategy, field):
        raise ValueError(f'Research daily latch changed: {strategy_id}/{field}')
    setattr(strategy, field, empty)
