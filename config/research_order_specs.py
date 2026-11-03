from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchOrderSpec:
    source: str
    name: str
    version: str
    timeframe: int
    reference_minutes: int
    allowed_tickers: tuple[str, ...] = ()


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


def setting_key(sid):
    return 'enable_' + sid.lower()


def execution_id(source, version, ticker=None):
    return next((sid for sid, spec in SPECS.items() if spec.source == source and spec.version == version
                 and (not spec.allowed_tickers or str(ticker or '').upper() in spec.allowed_tickers)), source)
