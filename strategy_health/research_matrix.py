"""Plain-language, account-scoped strategy/ticker research results."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json

from config.market_constants import COMMISSION_PER_CONTRACT
from config.strategy_catalog import (
    REVIEWED_STRATEGIES, reviewed_research_exit_minutes,
    reviewed_strategy_ids,
)
from strategy_health.candidate_evidence import candidate_signal_is_timely
from trading.tested_strategy_research import (
    enabled_tested_research_ids, strategy_details,
)

OPTION_SLIPPAGE_PER_SIDE = 0.01
EXIT_WINDOWS = (30, 60, 90)
QUOTE_WINDOW_GRACE_MINUTES = 5


def _parse_time(raw: object) -> datetime:
    parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _sample_time(row: object) -> datetime:
    """Return a comparable trigger time without trusting display formatting."""
    raw = row["trigger_bar"] or row["observed_at"]
    return _parse_time(raw)


def _independent_samples(samples: list, hold_minutes: int) -> list:
    """Collapse restart duplicates and fixed-hold overlaps into real episodes.

    A research worker can observe the same still-valid trigger more than once,
    especially after a restart.  A fixed-hold replay also cannot enter another
    position in the same strategy/ticker while the first one is still open.
    Counting either case as a new trade inflates sample size and profit factor.
    """
    accepted = []
    seen_triggers: set[tuple[str, str]] = set()
    next_entry_at: datetime | None = None
    for row in sorted(samples, key=_sample_time):
        trigger = str(row["trigger_bar"] or "").strip()
        dedupe_key = (
            str(row["direction"] or "").lower(),
            trigger or str(row["candidate_id"]),
        )
        if dedupe_key in seen_triggers:
            continue
        seen_triggers.add(dedupe_key)
        signal_time = _sample_time(row)
        if next_entry_at is not None and signal_time < next_entry_at:
            continue
        accepted.append(row)
        next_entry_at = signal_time + timedelta(minutes=max(1, int(hold_minutes)))
    return accepted


def _factor(profits: list[float]) -> float | str | None:
    wins = sum(value for value in profits if value > 0)
    losses = abs(sum(value for value in profits if value < 0))
    if not profits:
        return None
    if losses == 0:
        return "infinite" if wins > 0 else None
    return round(wins / losses, 2)


def _numeric_factor(value: object) -> float:
    return float("inf") if value == "infinite" else float(value or 0)


def _row_value(row: object, key: str) -> object:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _quote_measurement(row: object, exit_minutes: int) -> tuple[float | None, str | None]:
    """Return after-cost P&L and why an apparent result was not usable."""
    if exit_minutes not in EXIT_WINDOWS:
        return None, "unsupported_horizon"
    entry_raw = row["entry_ask"]
    exit_raw = row[f"bid_{exit_minutes}"]
    if entry_raw is None or exit_raw is None:
        return None, "missing_quote"
    entry = float(entry_raw)
    exit_bid = float(exit_raw)
    if entry <= 0 or exit_bid < 0:
        return None, "invalid_quote"
    entry_at = _row_value(row, "entry_quote_at")
    exit_at = _row_value(row, f"mark_{exit_minutes}_at")
    if entry_at and exit_at:
        elapsed = (_parse_time(exit_at) - _parse_time(entry_at)).total_seconds() / 60
        if elapsed < exit_minutes or elapsed > exit_minutes + QUOTE_WINDOW_GRACE_MINUTES:
            return None, "mistimed_quote"
    modeled_entry = entry + OPTION_SLIPPAGE_PER_SIDE
    modeled_exit = max(0.0, exit_bid - OPTION_SLIPPAGE_PER_SIDE)
    return round((modeled_exit - modeled_entry) * 100 - 2 * COMMISSION_PER_CONTRACT, 2), None


def _quote_profit(row: object, exit_minutes: int) -> float | None:
    """Return one-contract after-cost P&L only when both quotes really exist."""
    return _quote_measurement(row, exit_minutes)[0]


def _exit_summary(samples: list, exit_minutes: int) -> tuple[dict, list[tuple[str, float]]]:
    measured = [(row, _quote_measurement(row, exit_minutes)) for row in samples]
    dated_profits = [
        (str(row["observed_at"])[:10], result[0])
        for row, result in measured if result[0] is not None
    ]
    profits = [profit for _, profit in dated_profits]
    wins = sum(1 for profit in profits if profit > 0)
    return ({
        "minutes": exit_minutes,
        "option_results": len(profits),
        "wins": wins,
        "win_rate_pct": round(wins / len(profits) * 100, 1) if profits else None,
        "profit_factor": _factor(profits),
        "net_one_contract_pnl": round(sum(profits), 2),
        "mistimed_quotes_ignored": sum(result[1] == "mistimed_quote" for _, result in measured),
    }, dated_profits)


def _current_rule_samples(samples: list, strategy_id: str, ticker: str) -> tuple[list, int, int]:
    """Keep only candidates reconstructable under the currently deployed rule."""
    from trading.portfolio_policy import reviewed_strategy_entry_evidence_status

    eligible = []
    rejected = 0
    unscored = 0
    for row in samples:
        try:
            metadata = json.loads(str(_row_value(row, "metadata_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        status = reviewed_strategy_entry_evidence_status(
            ticker=ticker,
            strategy_id=strategy_id,
            direction=row["direction"],
            signal_meta=metadata,
        )
        if status in {"not_applicable", "passed"}:
            eligible.append(row)
        elif status == "rejected":
            rejected += 1
        else:
            unscored += 1
    return eligible, rejected, unscored


def _chronological_factors(dated_profits: list[tuple[str, float]]) -> tuple[object, object]:
    days = sorted({day for day, _ in dated_profits})
    if len(dated_profits) < 20 or len(days) < 8:
        return None, None
    split = min(max(5, int(len(days) * 0.7)), len(days) - 3)
    older_days = set(days[:split])
    older = [profit for day, profit in dated_profits if day in older_days]
    newer = [profit for day, profit in dated_profits if day not in older_days]
    return _factor(older), _factor(newer)


def research_status(
    *, results: int, days: int, sessions: int, factor: object,
    older_factor: object = None, newer_factor: object = None,
) -> tuple[str, str]:
    numeric = _numeric_factor(factor)
    if results >= 20 and days >= 8 and numeric >= 1.5:
        if newer_factor is not None and _numeric_factor(newer_factor) < 1.5:
            return "needs_tuning", "It worked on older dates but fell below 1.5 on newer dates."
        return "working", "PF is at least 1.5 across enough days."
    if results >= 20 and numeric < 1.0:
        return "not_working", "This version is losing and needs a change."
    if results >= 10 and numeric < 1.5:
        return "needs_tuning", "PF is below 1.5. Keep the data and tune the rule."
    if results >= 3 and numeric < 1.0:
        return "losing_so_far", "The first results are losing. Do not promote this pair yet."
    if results >= 5 and numeric >= 1.5:
        return "promising", "PF is above 1.5, but there are not enough results yet."
    if results:
        return "collecting", "More results are needed before judging it."
    if sessions >= 20:
        return "no_setups", "The bot watched this ticker but the setup did not appear."
    return "collecting", "The bot is still collecting market days."


def _diagnosis(
    *, status: str, setups: int, option_results: int, direction_results: int,
    direction_accuracy: float | None, factor: object, older_factor: object,
    newer_factor: object, exit_minutes: int, exit_summaries: list[dict],
) -> tuple[str, str]:
    if status == "working":
        return "ready", "Passed PF 1.5 and the minimum sample checks."
    if setups == 0:
        return "no_setups", "No setup yet. Keep watching."
    coverage = option_results / setups if setups else 0
    if setups >= 5 and coverage < 0.5:
        return "price_data", "Too many option prices are missing. Fix price data before judging it."
    if status == "losing_so_far":
        if direction_results >= 5 and direction_accuracy is not None:
            if direction_accuracy < 50:
                return "entry", "The stock moved the wrong way too often. Fix this pair's entry rule."
            if direction_accuracy >= 60:
                return "contract_exit", "The stock direction is working, but the option is losing. Test its contract and exit."
        return "early_loss", "This pair is losing so far. Keep collecting, but review its entry, option, and exit."
    if option_results < 10:
        return "more_data", "Not enough option results yet. Keep collecting."
    if older_factor is not None and newer_factor is not None:
        if _numeric_factor(older_factor) >= 1.5 and _numeric_factor(newer_factor) < 1.5:
            return "unstable", "Worked on older dates, but not newer dates. Retest the entry."
    alternatives = [
        summary for summary in exit_summaries
        if summary["minutes"] != exit_minutes and summary["option_results"] >= 10
    ]
    if alternatives:
        best = max(alternatives, key=lambda item: _numeric_factor(item["profit_factor"]))
        if _numeric_factor(best["profit_factor"]) >= 1.5 and _numeric_factor(factor) < 1.5:
            return "exit", f"The {best['minutes']}-minute exit tested better. Validate it on newer dates."
    if status == "promising":
        return "more_data", "PF is above 1.5, but the sample is too small. Keep collecting."
    if direction_results >= 10 and direction_accuracy is not None:
        if direction_accuracy < 50:
            return "entry", "The stock moved the wrong way too often. Fix the entry rule."
        if direction_accuracy >= 60 and _numeric_factor(factor) < 1.5:
            return "contract_exit", "The stock direction works, but the option does not. Test contract selection and exit."
    return "entry", "PF is below 1.5. Retest the entry rule before enabling it."


def build_research_matrix(days: int = 90) -> dict:
    from config import get_settings
    from database import get_conn, _now_et

    days = max(1, min(int(days), 365))
    settings = get_settings()
    account_id = settings.get("active_broker_account_id") or None
    cutoff = (_now_et() - timedelta(days=days)).isoformat()
    candidate_account = (
        "s.broker_account_id = ?" if account_id
        else "(s.broker_account_id IS NULL OR s.broker_account_id = '')"
    )
    candle_account = (
        "broker_account_id = ?" if account_id
        else "(broker_account_id IS NULL OR broker_account_id = '')"
    )
    params: tuple[object, ...] = (cutoff, account_id) if account_id else (cutoff,)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.candidate_id,s.observed_at,s.trigger_bar,s.ticker,s.strategy_id,
                      s.direction,s.metadata_json,
                      s.direction_correct,s.directional_move_pct,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.ask END) AS entry_ask,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.observed_at END) AS entry_quote_at,
                      MAX(CASE WHEN q.observation_kind='mark_30m' THEN q.bid END) AS bid_30,
                      MAX(CASE WHEN q.observation_kind='mark_30m' THEN q.observed_at END) AS mark_30_at,
                      MAX(CASE WHEN q.observation_kind='mark_60m' THEN q.bid END) AS bid_60,
                      MAX(CASE WHEN q.observation_kind='mark_60m' THEN q.observed_at END) AS mark_60_at,
                      MAX(CASE WHEN q.observation_kind='mark_90m' THEN q.bid END) AS bid_90,
                      MAX(CASE WHEN q.observation_kind='mark_90m' THEN q.observed_at END) AS mark_90_at
               FROM shadow_candidates s
               LEFT JOIN candidate_option_quote_observations q ON q.candidate_id=s.candidate_id
               WHERE s.observed_at >= ? AND """ + candidate_account +
            " GROUP BY s.candidate_id ORDER BY s.observed_at",
            params,
        ).fetchall()
        candle_params: tuple[object, ...] = (cutoff[:10], account_id) if account_id else (cutoff[:10],)
        exposure = conn.execute(
            "SELECT ticker,substr(bar_time,1,10) AS evidence_day "
            "FROM scanner_candle_observations WHERE bar_time >= ? AND "
            + candle_account + " GROUP BY ticker,evidence_day",
            candle_params,
        ).fetchall()

    # Candle archiving was introduced after candidate recording.  A ticker can
    # therefore have genuine older candidate evidence while having no matching
    # scanner-candle row.  Counting only the newer table made the UI claim
    # "0 days watched" beside a real saved result.  The union is the honest
    # lower bound: every candle day and every candidate day is a day with data.
    evidence_days: dict[str, set[str]] = defaultdict(set)
    for row in exposure:
        evidence_days[str(row["ticker"]).upper()].add(str(row["evidence_day"])[:10])
    for row in rows:
        evidence_days[str(row["ticker"]).upper()].add(str(row["observed_at"])[:10])
    sessions = {ticker: len(dates) for ticker, dates in evidence_days.items()}
    tickers = set(sessions) | {str(value).upper() for value in settings.get("watchlist", [])}
    tickers |= {str(row["ticker"]).upper() for row in rows}
    catalog_ids = {
        strategy_id for strategy_id in reviewed_strategy_ids()
        if not REVIEWED_STRATEGIES[strategy_id].observation_only
        or bool(settings.get(REVIEWED_STRATEGIES[strategy_id].setting_key, False))
    }
    runtime_ids = enabled_tested_research_ids(settings)
    strategy_ids = sorted(catalog_ids | runtime_ids)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        grouped[(str(row["strategy_id"]).upper(), str(row["ticker"]).upper())].append(row)

    strategy_rows = []
    for strategy_id in strategy_ids:
        rule = REVIEWED_STRATEGIES.get(strategy_id)
        runtime = strategy_details(strategy_id)
        display_name = rule.display_name if rule else runtime.display_name
        exit_minutes = (
            reviewed_research_exit_minutes(strategy_id)
            if rule else (runtime.exit_minutes if runtime else 90)
        )
        pairs = []
        for ticker in sorted(tickers):
            raw_samples = grouped.get((strategy_id, ticker), [])
            timely_samples = [
                row for row in raw_samples if candidate_signal_is_timely(row)
            ]
            stale_or_replayed = len(raw_samples) - len(timely_samples)
            rule_samples, rule_rejected, rule_unscored = _current_rule_samples(
                timely_samples, strategy_id, ticker,
            )
            samples = _independent_samples(rule_samples, exit_minutes)
            exit_summaries = []
            current_results: list[tuple[str, float]] = []
            current_summary = None
            for window in EXIT_WINDOWS:
                window_samples = _independent_samples(rule_samples, window)
                summary, results = _exit_summary(window_samples, window)
                exit_summaries.append(summary)
                if window == exit_minutes:
                    current_summary, current_results = summary, results
            if current_summary is None:
                current_summary = {
                    "minutes": exit_minutes, "option_results": 0, "wins": 0,
                    "win_rate_pct": None, "profit_factor": None,
                    "net_one_contract_pnl": 0.0,
                    "mistimed_quotes_ignored": 0,
                }
            factor = current_summary["profit_factor"]
            option_result_days = len({day for day, _ in current_results})
            older_factor, newer_factor = _chronological_factors(current_results)
            status, explanation = research_status(
                results=current_summary["option_results"], days=option_result_days,
                sessions=sessions.get(ticker, 0), factor=factor,
                older_factor=older_factor, newer_factor=newer_factor,
            )
            correct = sum(1 for row in samples if row["direction_correct"] == 1)
            measured = sum(1 for row in samples if row["direction_correct"] is not None)
            direction_accuracy = round(correct / measured * 100, 1) if measured else None
            diagnosis, next_action = _diagnosis(
                status=status, setups=len(samples),
                option_results=current_summary["option_results"],
                direction_results=measured, direction_accuracy=direction_accuracy,
                factor=factor, older_factor=older_factor, newer_factor=newer_factor,
                exit_minutes=exit_minutes, exit_summaries=exit_summaries,
            )
            pairs.append({
                "ticker": ticker,
                "status": status,
                "explanation": explanation,
                "market_days": sessions.get(ticker, 0),
                "setups": len(samples),
                "raw_observations": len(raw_samples),
                "rule_rejected": rule_rejected,
                "rule_unscored": rule_unscored,
                "stale_or_replayed": stale_or_replayed,
                "option_results": current_summary["option_results"],
                "option_result_days": option_result_days,
                "wins": current_summary["wins"],
                "win_rate_pct": current_summary["win_rate_pct"],
                "profit_factor": factor,
                "net_one_contract_pnl": current_summary["net_one_contract_pnl"],
                "direction_results": measured,
                "direction_accuracy": direction_accuracy,
                "quote_coverage_pct": round(current_summary["option_results"] / len(samples) * 100, 1) if samples else None,
                "mistimed_quotes_ignored": current_summary["mistimed_quotes_ignored"],
                "older_profit_factor": older_factor,
                "newer_profit_factor": newer_factor,
                "diagnosis": diagnosis,
                "next_action": next_action,
                "exit_comparison": exit_summaries,
                "tradable": bool(rule and not rule.observation_only and ticker in rule.tickers),
            })
        priority = {"working": 0, "promising": 1, "losing_so_far": 2, "needs_tuning": 3, "not_working": 4, "collecting": 5, "no_setups": 6}
        strategy_rows.append({
            "strategy_id": strategy_id,
            "display_name": display_name,
            "research_enabled": True,
            "trading_tickers": sorted(rule.tickers) if rule and not rule.observation_only else [],
            "exit_minutes": exit_minutes,
            "pairs": sorted(pairs, key=lambda pair: (priority[pair["status"]], pair["ticker"])),
        })
    return {
        "days": days,
        "target_profit_factor": 1.5,
        "cost_model": f"saved ask to bid within {QUOTE_WINDOW_GRACE_MINUTES} minutes of the named exit, ${OPTION_SLIPPAGE_PER_SIDE:.2f} adverse slippage per side, ${COMMISSION_PER_CONTRACT:.2f} fee per side",
        "account_scoped": bool(account_id),
        "ticker_count": len(tickers),
        "strategy_count": len(strategy_rows),
        "strategies": strategy_rows,
    }
