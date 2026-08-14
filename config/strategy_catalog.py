"""Reviewed strategy scope used by scanning and order routing.

The scanner deliberately has a broad job: find liquid names with movement.
This catalog has a narrow one: declare which *strategy/ticker combinations*
have actually passed the paid-quote review.  Keeping those concerns separate
lets a strategy later prove repeatable on more symbols without turning a
single-symbol result into an unsupported universal claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ReviewedStrategy:
    strategy_id: str
    tickers: frozenset[str]
    setting_key: str
    exit_minutes: int | None
    evidence: str


REVIEWED_STRATEGIES: dict[str, ReviewedStrategy] = {
    "V2_ORB_PULLBACK": ReviewedStrategy(
        strategy_id="V2_ORB_PULLBACK",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_orb_pullback_v2_enabled",
        exit_minutes=90,
        evidence="TSLA paid-quote one-minute calls-only opening-range first-retouch study (entry by 10:30 ET)",
    ),
    "V2_SPY_TREND_CONT": ReviewedStrategy(
        strategy_id="V2_SPY_TREND_CONT",
        tickers=frozenset({"SPY"}),
        setting_key="strategy_spy_trend_cont_v2_enabled",
        # The actual bot permits one SPY position at a time.  Under that same
        # account constraint, the 30-minute fixed hold was selected on earlier
        # paid data and passed the untouched later period (66 later trades).
        # The longer per-signal scan allowed overlapping SPY positions and is
        # diagnostic only, not the executable policy.
        exit_minutes=30,
        evidence="SPY paid-quote Trend Continuation 30-minute one-position fixed-hold study",
    ),
    "V2_TSLA_NOISE_MOMENTUM": ReviewedStrategy(
        strategy_id="V2_TSLA_NOISE_MOMENTUM",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_tsla_noise_momentum_v2_enabled",
        exit_minutes=None,
        evidence="TSLA paid-quote 14-prior-session adaptive noise-boundary momentum study; next-minute entry and 15:59 ET same-contract exit",
    ),
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": ReviewedStrategy(
        strategy_id="V2_TSLA_TWO_LEG_TREND_PULLBACK",
        tickers=frozenset({"TSLA"}),
        setting_key="strategy_tsla_two_leg_trend_pullback_v2_enabled",
        exit_minutes=90,
        evidence="TSLA paid-quote one-minute VWAP/EMA two-leg pullback study; next-minute option ask and same-contract 90-minute bid",
    ),
}


def reviewed_strategy_ids() -> set[str]:
    """Return server-reviewed IDs; browser settings cannot invent one."""
    return set(REVIEWED_STRATEGIES)


def is_allowed_ticker(strategy_id: object, ticker: object) -> bool:
    """Return whether a reviewed strategy may run on this ticker."""
    rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
    return bool(rule and str(ticker or "").strip().upper() in rule.tickers)


def enabled_reviewed_strategy_ids(settings: dict) -> set[str]:
    """Return reviewed strategies whose separate Settings switch is on."""
    return {
        strategy_id
        for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if bool(settings.get(rule.setting_key, False))
    }


def ensure_reviewed_ticker_coverage(
    watchlist: Iterable[object], enabled_strategy_ids: Iterable[object],
) -> list[str]:
    """Keep the scanner's ranked list, appending only required pilot symbols.

    A daily scanner may rightly omit a quieter symbol.  An explicitly enabled
    reviewed setup still needs to be observed, so this only adds its validated
    ticker; it never replaces the scan's dynamic universe or changes ranking.
    """
    result = list(dict.fromkeys(
        str(ticker).strip().upper() for ticker in watchlist if str(ticker).strip()
    ))
    for strategy_id in sorted(str(value).strip().upper() for value in enabled_strategy_ids):
        rule = REVIEWED_STRATEGIES.get(str(strategy_id or "").strip().upper())
        if rule is None:
            continue
        for ticker in sorted(rule.tickers):
            if ticker not in result:
                result.append(ticker)
    return result
