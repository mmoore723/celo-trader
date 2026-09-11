"""Run reconstructed, order-free strategy tests on every collected ticker."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time, timedelta
import logging
from typing import Callable, Iterable

import pandas as pd

from research.engine.data import resample_regular_session
from research.engine.models import Bar as ResearchBar, Side
from research.engine.strategies import (
    AfternoonCompressionBreakout, AfternoonCompressionBreakoutConfig,
    AfternoonReversal, EMAPullbackRTH, FairValueGap, GapFillRTH,
    ImpulseAnchoredVwapConfig, ImpulseAnchoredVwapPullback,
    MiddayBreakdown, OpeningMomentumRTH, OpeningRangeBreakout,
    ORBRsiMacdShort, SuperTrendReversal, TrendContinuation,
    TurtleSoupRTH, VWAPPullback, VWAPReversionRTH, RangeSweepReclaim, RangeSweepReclaimConfig,
)
from strategies.base import Signal
from strategy_health.exit_protocols import candidate_metadata
from trading.research_emission import POLICY as EMISSION_POLICY, EXPANDED_IDS, prepare_bar

logger = logging.getLogger("celo_trader.research")


@dataclass(frozen=True)
class TestedResearchStrategy:
    strategy_id: str
    display_name: str
    factory: Callable[[], object]
    version: str = "research.1"
    exit_minutes: int = 90
    timeframe_minutes: int = 5
    allowed_sides: frozenset[Side] | None = None
    implementation: str | None = None


_LEGACY_DEFAULT_IDS = (
    "V2_AFTERNOON_REVERSAL", "V2_EMA_PULLBACK_RTH", "V2_FAIR_VALUE_GAP",
    "V2_GAP_FILL_RTH", "V2_MIDDAY_BREAKDOWN",
    "V2_OPENING_MOMENTUM_RTH_EXPLORATORY", "V2_ORB_CONFIRMED_BREAKOUT",
    "V2_SPY_ORB_RSI_MACD_SHORT", "V2_TREND_CONT", "V2_TURTLE_SOUP_RTH",
    "V2_VWAP_PULLBACK", "V2_VWAP_REVERSION_RTH", "TV_SUPERTREND_REVERSAL_V4",
)


_SPECS = (
    TestedResearchStrategy(
        "V2_AFTERNOON_COMPRESSION_BREAKOUT", "Afternoon Compression Breakout",
        lambda: AfternoonCompressionBreakout(AfternoonCompressionBreakoutConfig(
            max_compression_pct=.004, entry_end=time(15, 0),
        )), exit_minutes=30, timeframe_minutes=1,
    ),
    TestedResearchStrategy("V2_AFTERNOON_REVERSAL", "Afternoon Reversal", AfternoonReversal),
    TestedResearchStrategy(
        "V2_EMA_PULLBACK_RTH", "EMA Pullback", EMAPullbackRTH,
        timeframe_minutes=15, version="research.3",
    ),
    TestedResearchStrategy("V2_FAIR_VALUE_GAP", "Fair Value Gap", FairValueGap),
    TestedResearchStrategy("V2_GAP_FILL_RTH", "Gap Fill", GapFillRTH),
    TestedResearchStrategy("V2_MIDDAY_BREAKDOWN", "Midday Breakdown", MiddayBreakdown),
    TestedResearchStrategy("V2_OPENING_MOMENTUM_RTH_EXPLORATORY", "Opening Momentum", OpeningMomentumRTH),
    TestedResearchStrategy("V2_ORB_CONFIRMED_BREAKOUT", "Confirmed Opening-Range Breakout", OpeningRangeBreakout),
    TestedResearchStrategy(
        "V2_IMPULSE_ANCHORED_VWAP_PULLBACK", "Impulse Anchored VWAP Pullback",
        lambda: ImpulseAnchoredVwapPullback(ImpulseAnchoredVwapConfig(
            stop_buffer_atr=.50, target_r=2.0,
        )), exit_minutes=120,
    ),
    TestedResearchStrategy(
        "V2_RANGE_SWEEP_RECLAIM",
        "Range Sweep Reclaim (Calls)",
        lambda: RangeSweepReclaim(RangeSweepReclaimConfig(
            range_bars=30, maximum_efficiency=.30, minimum_sweep_atr=.15,
        )),
        exit_minutes=30, timeframe_minutes=1,
        allowed_sides=frozenset({Side.LONG}),
    ),
    TestedResearchStrategy("V2_SPY_ORB_RSI_MACD_SHORT", "ORB RSI/MACD Short", ORBRsiMacdShort),
    TestedResearchStrategy("V2_TREND_CONT", "Trend Continuation", TrendContinuation),
    TestedResearchStrategy("V2_TURTLE_SOUP_RTH", "Turtle Soup Reversal", TurtleSoupRTH),
    TestedResearchStrategy("V2_VWAP_PULLBACK", "VWAP Pullback", VWAPPullback),
    TestedResearchStrategy("V2_VWAP_REVERSION_RTH", "VWAP Reversion", VWAPReversionRTH),
    TestedResearchStrategy("TV_SUPERTREND_REVERSAL_V4", "SuperTrend Reversal", SuperTrendReversal),
)
_SPECS = tuple(replace(item, version='research.2') if item.strategy_id in EXPANDED_IDS and item.version == 'research.1' else item for item in _SPECS)
TESTED_RESEARCH_STRATEGIES = {item.strategy_id: item for item in _SPECS}
DEFAULT_TESTED_RESEARCH_IDS = tuple(TESTED_RESEARCH_STRATEGIES)
_emitted: set[tuple[str, str, str, str]] = set()


def enabled_tested_research_ids(settings: dict) -> set[str]:
    selected = settings.get("research_strategy_ids", DEFAULT_TESTED_RESEARCH_IDS)
    if not isinstance(selected, (list, tuple, set)):
        selected = DEFAULT_TESTED_RESEARCH_IDS
    enabled = {str(value).upper() for value in selected}
    # Add newly reconstructed, order-free rules only for accounts that still
    # had every prior default selected. A deliberately paused list is kept.
    if set(_LEGACY_DEFAULT_IDS).issubset(enabled):
        enabled.update(DEFAULT_TESTED_RESEARCH_IDS)
    return enabled & set(TESTED_RESEARCH_STRATEGIES)


def public_tested_research_strategies(settings: dict) -> list[dict]:
    enabled = enabled_tested_research_ids(settings)
    return [
        {
            "strategy_id": item.strategy_id,
            "display_name": item.display_name,
            "version": item.version,
            "exit_minutes": item.exit_minutes,
            "timeframe_minutes": item.timeframe_minutes,
            "enabled": item.strategy_id in enabled,
            "research_scope": "all_collected_tickers",
        }
        for item in _SPECS
    ]


def strategy_details(strategy_id: object) -> TestedResearchStrategy | None:
    return TESTED_RESEARCH_STRATEGIES.get(str(strategy_id or "").strip().upper())


def _research_bars(
    frame: pd.DataFrame, now: object | None, timeframe_minutes: int,
) -> tuple[ResearchBar, ...]:
    required = {"time", "open", "high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return ()
    rows = frame[list(required)].copy()
    rows["time"] = pd.to_datetime(rows["time"])
    if rows["time"].dt.tz is not None:
        rows["time"] = rows["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    rows = rows.sort_values("time").drop_duplicates("time", keep="last")
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    cutoff = cutoff.floor("min")
    rows = rows.loc[
        (rows["time"] < cutoff)
        & (rows["time"].dt.time >= time(9, 30))
        & (rows["time"].dt.time < time(16, 0))
    ]
    one_minute = tuple(
        ResearchBar(
            pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
            float(row.low), float(row.close), float(row.volume or 0),
        )
        for row in rows.itertuples(index=False)
    )
    bars = resample_regular_session(
        one_minute, source_minutes=1, target_minutes=timeframe_minutes,
    )
    return tuple(bars[-500:])


def _latest_candidate(strategy: object, bars: tuple[ResearchBar, ...], *, research_strategy_id: str | None = None):
    """Replay completed bars once and return only a signal on the newest bar."""
    history: list[ResearchBar] = []
    latest = None
    for bar in bars:
        history.append(bar)
        if research_strategy_id is not None:
            prepare_bar(research_strategy_id, strategy)
        candidate = strategy.evaluate(history)
        if candidate is not None:
            latest = candidate
    if latest is not None and latest.timestamp == bars[-1].timestamp:
        return latest
    return None


def evaluate_tested_research(
    frame: pd.DataFrame, ticker: str, strategy_ids: Iterable[str], *,
    scope: str, now: object | None = None, history_5m: pd.DataFrame | None = None,
    history_15m: pd.DataFrame | None = None,
) -> list[Signal]:
    results: list[Signal] = []
    bars_by_timeframe: dict[int, tuple[ResearchBar, ...]] = {}
    for strategy_id in strategy_ids:
        spec = strategy_details(strategy_id)
        if spec is None:
            continue
        if spec.timeframe_minutes not in bars_by_timeframe:
            bars_by_timeframe[spec.timeframe_minutes] = _research_bars(
                frame, now, spec.timeframe_minutes,
            )
        bars = bars_by_timeframe[spec.timeframe_minutes]
        if spec.strategy_id == "V2_EMA_PULLBACK_RTH":
            from trading.research_ema_history import with_ema_history
            bars = with_ema_history(bars, history_5m, now)
            if history_15m is not None:
                from trading.research_ema_history import with_native_ema_history
                bars=with_native_ema_history(bars,history_15m,now)
        if not bars:
            continue
        try:
            strategy = spec.factory()
            candidate = _latest_candidate(strategy, bars, research_strategy_id=spec.strategy_id)
        except Exception:
            logger.warning("Tested strategy research failed for %s/%s", strategy_id, ticker, exc_info=True)
            continue
        if candidate is None:
            continue
        if spec.allowed_sides is not None and candidate.side not in spec.allowed_sides:
            continue
        key = (scope, ticker.upper(), spec.strategy_id, candidate.timestamp.isoformat())
        if key in _emitted:
            continue
        _emitted.add(key)
        results.append(Signal(
            strategy_id=spec.strategy_id,
            direction="bullish" if candidate.side is Side.LONG else "bearish",
            confidence=0.70,
            rvol=0.0,
            trigger_bar=pd.Timestamp(candidate.timestamp) + timedelta(minutes=spec.timeframe_minutes),
            meta={
                **dict(candidate.features),
                "strategy_version": spec.version,
                "research_emission_policy": EMISSION_POLICY,
                "implementation": spec.implementation or strategy.__class__.__module__,
                "research_library": True,
                "timeframe_minutes": spec.timeframe_minutes,
                "entry_timing": f"completed_{spec.timeframe_minutes}m_signal_then_next_quote",
                "underlying_stop": candidate.stop,
                "underlying_target": candidate.target,
                "exit_plan": f"same-contract bid after {spec.exit_minutes} minutes",
                "observation_only": True,
                **({"history_policy": ("complete_15m_collected_preferred_native15_v1" if history_15m is not None
                                       else "complete_15m_collected_preferred_fetched5m_gaps_v1")}
                   if spec.strategy_id == "V2_EMA_PULLBACK_RTH" else {}),
                **candidate_metadata(spec.strategy_id, strategy),
            },
        ))
    return results
