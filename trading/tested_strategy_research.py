"""Run reconstructed, order-free strategy tests on every collected ticker."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
import logging
from typing import Callable, Iterable

import pandas as pd

from research.engine.models import Bar as ResearchBar, Side
from research.engine.strategies import (
    AfternoonReversal, EMAPullbackRTH, FairValueGap, GapFillRTH,
    MiddayBreakdown, OpeningMomentumRTH, OpeningRangeBreakout,
    ORBRsiMacdShort, SuperTrendReversal, TrendContinuation,
    TurtleSoupRTH, VWAPPullback, VWAPReversionRTH,
)
from strategies.base import Signal
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars

logger = logging.getLogger("celo_trader.research")


@dataclass(frozen=True)
class TestedResearchStrategy:
    strategy_id: str
    display_name: str
    factory: Callable[[], object]
    version: str = "research.1"
    exit_minutes: int = 90


_SPECS = (
    TestedResearchStrategy("V2_AFTERNOON_REVERSAL", "Afternoon Reversal", AfternoonReversal),
    TestedResearchStrategy("V2_EMA_PULLBACK_RTH", "EMA Pullback", EMAPullbackRTH),
    TestedResearchStrategy("V2_FAIR_VALUE_GAP", "Fair Value Gap", FairValueGap),
    TestedResearchStrategy("V2_GAP_FILL_RTH", "Gap Fill", GapFillRTH),
    TestedResearchStrategy("V2_MIDDAY_BREAKDOWN", "Midday Breakdown", MiddayBreakdown),
    TestedResearchStrategy("V2_OPENING_MOMENTUM_RTH_EXPLORATORY", "Opening Momentum", OpeningMomentumRTH),
    TestedResearchStrategy("V2_ORB_CONFIRMED_BREAKOUT", "Confirmed Opening-Range Breakout", OpeningRangeBreakout),
    TestedResearchStrategy("V2_SPY_ORB_RSI_MACD_SHORT", "ORB RSI/MACD Short", ORBRsiMacdShort),
    TestedResearchStrategy("V2_TREND_CONT", "Trend Continuation", TrendContinuation),
    TestedResearchStrategy("V2_TURTLE_SOUP_RTH", "Turtle Soup Reversal", TurtleSoupRTH),
    TestedResearchStrategy("V2_VWAP_PULLBACK", "VWAP Pullback", VWAPPullback),
    TestedResearchStrategy("V2_VWAP_REVERSION_RTH", "VWAP Reversion", VWAPReversionRTH),
    TestedResearchStrategy("TV_SUPERTREND_REVERSAL_V4", "SuperTrend Reversal", SuperTrendReversal),
)
TESTED_RESEARCH_STRATEGIES = {item.strategy_id: item for item in _SPECS}
DEFAULT_TESTED_RESEARCH_IDS = tuple(TESTED_RESEARCH_STRATEGIES)
_emitted: set[tuple[str, str, str, str]] = set()


def enabled_tested_research_ids(settings: dict) -> set[str]:
    selected = settings.get("research_strategy_ids", DEFAULT_TESTED_RESEARCH_IDS)
    if not isinstance(selected, (list, tuple, set)):
        selected = DEFAULT_TESTED_RESEARCH_IDS
    return {str(value).upper() for value in selected} & set(TESTED_RESEARCH_STRATEGIES)


def public_tested_research_strategies(settings: dict) -> list[dict]:
    enabled = enabled_tested_research_ids(settings)
    return [
        {
            "strategy_id": item.strategy_id,
            "display_name": item.display_name,
            "version": item.version,
            "exit_minutes": item.exit_minutes,
            "enabled": item.strategy_id in enabled,
            "research_scope": "all_collected_tickers",
        }
        for item in _SPECS
    ]


def strategy_details(strategy_id: object) -> TestedResearchStrategy | None:
    return TESTED_RESEARCH_STRATEGIES.get(str(strategy_id or "").strip().upper())


def _research_bars(frame: pd.DataFrame, now: object | None) -> tuple[ResearchBar, ...]:
    required = {"time", "open", "high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return ()
    rows = frame[list(required)].copy()
    rows["time"] = pd.to_datetime(rows["time"])
    if rows["time"].dt.tz is not None:
        rows["time"] = rows["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    rows = rows.sort_values("time").drop_duplicates("time", keep="last")
    current_date = rows["time"].dt.date.max()
    prior = rows.loc[rows["time"].dt.date < current_date]
    current = rows.loc[rows["time"].dt.date == current_date]
    current_bars = _complete_five_minute_bars(current, now=now)
    combined = [
        ResearchBar(
            pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
            float(row.low), float(row.close), float(row.volume or 0),
        )
        for row in prior.itertuples(index=False)
        if row.time.time() >= time(9, 30)
        and row.time.time() < time(16, 0)
    ]
    combined.extend(
        ResearchBar(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for bar in current_bars
    )
    return tuple(combined[-1600:])


def evaluate_tested_research(
    frame: pd.DataFrame, ticker: str, strategy_ids: Iterable[str], *,
    scope: str, now: object | None = None,
) -> list[Signal]:
    bars = _research_bars(frame, now)
    if not bars:
        return []
    results: list[Signal] = []
    for strategy_id in strategy_ids:
        spec = strategy_details(strategy_id)
        if spec is None:
            continue
        try:
            strategy = spec.factory()
            candidate = strategy.evaluate(bars)
        except Exception:
            logger.warning("Tested strategy research failed for %s/%s", strategy_id, ticker, exc_info=True)
            continue
        if candidate is None:
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
            trigger_bar=pd.Timestamp(candidate.timestamp) + timedelta(minutes=5),
            meta={
                **dict(candidate.features),
                "strategy_version": spec.version,
                "implementation": strategy.__class__.__module__,
                "research_library": True,
                "entry_timing": "completed_5m_signal_then_next_quote",
                "underlying_stop": candidate.stop,
                "underlying_target": candidate.target,
                "exit_plan": f"same-contract bid after {spec.exit_minutes} minutes",
                "observation_only": True,
            },
        ))
    return results
