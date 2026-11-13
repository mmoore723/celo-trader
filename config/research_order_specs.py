from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchOrderSpec:
    source: str
    name: str
    version: str
    timeframe: int
    reference_minutes: int
    allowed_tickers: tuple[str, ...] = ()
    adapter: str = 'library'


SPECS = {
    'V2_VWAP_PULLBACK': ResearchOrderSpec('V2_VWAP_PULLBACK', 'VWAP Pullback', 'research.1', 5, 90, ('AMZN',)),
    'RESEARCH_QQQ_TREND_V2': ResearchOrderSpec('V2_SPY_TREND_CONT', 'Trend Continuation', '2.1.0', 5, 30, ('QQQ',)),
    'V2_AFTERNOON_COMPRESSION_BREAKOUT': ResearchOrderSpec('V2_AFTERNOON_COMPRESSION_BREAKOUT', 'Afternoon Compression Breakout', 'research.2', 1, 30),
    'V2_GAP_FILL_RTH': ResearchOrderSpec('V2_GAP_FILL_RTH', 'Gap Fill', 'research.2', 5, 90),
    'V2_AFTERNOON_REVERSAL': ResearchOrderSpec('V2_AFTERNOON_REVERSAL', 'Afternoon Reversal', 'research.1', 5, 90),
    'V2_SPY_ORB_RSI_MACD_SHORT': ResearchOrderSpec('V2_SPY_ORB_RSI_MACD_SHORT', 'ORB RSI/MACD Short', 'research.2', 5, 90),
    'V2_IMPULSE_ANCHORED_VWAP_PULLBACK': ResearchOrderSpec('V2_IMPULSE_ANCHORED_VWAP_PULLBACK', 'Impulse Anchored VWAP Pullback', 'research.2', 5, 120),
    'RESEARCH_CTX_ORB_ATR10_V2': ResearchOrderSpec('CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG', 'Context-Filtered ORB (ATR10)', '0.1.0.research.2', 1, 90),
    'RESEARCH_FAILED_RANGE_V2': ResearchOrderSpec('V2_FAILED_OR_BREAK_VWAP_REVERSION', 'Failed-Range Recovery', '2.1.0.research.2', 1, 30),
}


# One shared adapter per exact research version. No ticker receives permission
# from this registry: account approval remains the execution whitelist.
EXTENDED = {
    'V2_EMA_PULLBACK_RTH': ('EMA Pullback', 'research.3', 15, 90, 'library'),
    'V2_FAIR_VALUE_GAP': ('Fair Value Gap', 'research.1', 5, 90, 'library'),
    'V2_MIDDAY_BREAKDOWN': ('Midday Breakdown', 'research.2', 5, 90, 'library'),
    'V2_OPENING_MOMENTUM_RTH_EXPLORATORY': ('Opening Momentum', 'research.1', 5, 90, 'library'),
    'V2_ORB_CONFIRMED_BREAKOUT': ('Confirmed Opening-Range Breakout', 'research.2', 5, 90, 'library'),
    'V2_RANGE_SWEEP_RECLAIM': ('Range Sweep Reclaim (Calls)', 'research.1', 1, 30, 'library'),
    'V2_TURTLE_SOUP_RTH': ('Turtle Soup Reversal', 'research.1', 5, 90, 'library'),
    'V2_VWAP_REVERSION_RTH': ('VWAP Reversion', 'research.2', 5, 90, 'library'),
    'TV_SUPERTREND_REVERSAL_V4': ('SuperTrend Reversal', 'research.1', 5, 90, 'library'),
    'V2_VWAP_PULLBACK': ('VWAP Pullback', 'research.1', 5, 90, 'library'),
    'V2_TREND_CONT': ('Trend Continuation', 'research.1', 5, 90, 'library'),
    'V2_SPY_TREND_CONT': ('Trend Continuation', '2.1.0', 5, 30, 'native_trend'),
    'V2_SPY_AFTERNOON_FVG': ('Afternoon Fair Value Gap', '2.1.0', 5, 30, 'native_fvg'),
    'CTX_ORB_NR7_OR_INSIDE': ('Context-Filtered ORB (NR7 / Inside)', '0.1.0.research.2', 1, 90, 'context'),
    'CTX_VWAP_PULLBACK_KER10_LONG': ('VWAP Pullback (1-Hour KER)', '0.1.0.research.2', 5, 90, 'context'),
    'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG': ('VWAP 10:30 Displacement', '0.2.0.research.2', 5, 90, 'context'),
    'CTX_1H_SQUEEZE_MACD_LONG': ('Hourly Squeeze', '0.1.0', 60, 90, 'squeeze'),
    'V2_ORB_PULLBACK': ('Opening-Range Pullback', '2.0.0.research.2', 1, 90, 'retouch'),
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('Two-Leg Trend Pullback', '2.1.0.research.2', 1, 90, 'two_leg'),
}
for _source, (_name, _version, _tf, _minutes, _adapter) in EXTENDED.items():
    SPECS['APPROVED_' + _source] = ResearchOrderSpec(_source, _name, _version, _tf, _minutes, adapter=_adapter)

# Existing native assignments win. Adding support must not reroute an active pair.
LEGACY_NATIVE = {
    ('V2_SPY_TREND_CONT', '2.1.0'): frozenset({'SPY'}),
    ('V2_SPY_AFTERNOON_FVG', '2.1.0'): frozenset({'SPY'}),
    ('V2_TREND_CONT', 'research.1'): frozenset({'SPY', 'QQQ'}),
}


def setting_key(sid):
    return 'enable_' + sid.lower()


def execution_id(source, version, ticker=None):
    if str(ticker or '').upper() in LEGACY_NATIVE.get((source, version), ()):
        return source
    return next((sid for sid, spec in SPECS.items() if spec.source == source and spec.version == version
                 and (not spec.allowed_tickers or str(ticker or '').upper() in spec.allowed_tickers)), source)
