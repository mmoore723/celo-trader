"""Plain-language, account-scoped strategy/ticker research results."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from statistics import median

from config.market_constants import COMMISSION_PER_CONTRACT
from config.strategy_catalog import (
    REVIEWED_STRATEGIES, _backtest_display, enabled_reviewed_strategy_ids, reviewed_research_exit_minutes,
    reviewed_strategy_ids,
)
from strategy_health.candidate_evidence import candidate_signal_is_timely
from strategy_health.exit_measurement import exit_measurement
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary
from strategy_health.exit_protocols import PROTOCOLS
from database.option_profit_protection import load as load_profit_tests
from database.reference_contract_tests import load as load_reference_tests, summary as reference_summary
from database.expiration_study import load as load_expiration_studies
from strategy_health.expiration_study_summary import summary as expiration_study_summary
from strategy_health.option_profit_protection import summary as profit_test_summary, PROTOCOL_BY_STRATEGY
from strategy_health.ticker_qualification import DEFAULT_POLICY
from strategy_health.pair_recommendations import POLICY, assess, summarize, timestamp
from strategy_health.authored_exit_summary import net_profit
from trading.tested_strategy_research import (
    enabled_tested_research_ids, strategy_details,
)
from trading.research_versions import evidence_version
from trading.research_contract_selection import (
    RESEARCH_CONTRACT_PROFILE_VERSION, RESEARCH_CONTRACT_SOURCE,
)
from database.option_quotes import CANDIDATE_MARK_HORIZONS

OPTION_SLIPPAGE_PER_SIDE = 0.01
EXIT_WINDOWS = CANDIDATE_MARK_HORIZONS
QUOTE_WINDOW_GRACE_MINUTES = 5
ENTRY_TUNING_MARKET_DAYS = 10
CONTRACT_POLICY_LABELS = {
    "target_150_250": "$150–$250 closest to $200",
    "nearest_weekly_150_1000": "Nearest weekly $150–$1,000",
    "closest_otm_150_1000": "Closest OTM $150–$1,000",
    "tightest_spread_150_1000": "Tightest spread $150–$1,000",
    "lowest_ask_150_1000": "Lowest ask $150–$1,000",
    "highest_open_interest_150_1000": "Highest open interest $150–$1,000",
    "highest_volume_150_1000": "Highest volume $150–$1,000",
}


def _parse_time(raw: object) -> datetime:
    parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _sample_time(row: object) -> datetime:
    """Return a comparable trigger time without trusting display formatting."""
    raw = row["trigger_bar"] or row["observed_at"]
    return _parse_time(raw)


def _distinct_samples(samples: list, _hold_minutes: int, *, preferred_source: str | None = None) -> list:
    """Keep every distinct research play; collapse exact restart duplicates.

    Research may model many overlapping hypothetical positions.  Paper/live
    portfolio limits do not apply here.  Only the same direction and exact
    trigger timestamp is a duplicate rather than a new play.
    """
    accepted = []
    seen_triggers: set[tuple[str, str]] = set()
    # A native order preview and an all-setups research candidate can share
    # a trigger. Select the intended cohort before deduplication, never by
    # which one later wins or obtains a complete exit quote.
    for row in sorted(samples, key=lambda row: (
        _sample_time(row),
        preferred_source is not None and _row_value(row, "entry_source") != preferred_source,
    )):
        trigger = str(row["trigger_bar"] or "").strip()
        dedupe_key = (
            str(row["direction"] or "").lower(),
            trigger or str(row["candidate_id"]),
        )
        if dedupe_key in seen_triggers:
            continue
        seen_triggers.add(dedupe_key)
        accepted.append(row)
    return accepted


def _factor(profits: list[float]) -> float | str | None:
    wins = sum(value for value in profits if value > 0)
    losses = abs(sum(value for value in profits if value < 0))
    if not profits:
        return None
    if losses == 0:
        return "infinite" if wins > 0 else None
    return round(wins / losses, 2)


def _distribution_summary(profits: list[float]) -> dict[str, float | None]:
    """Describe both the typical result and path risk without hiding skew."""
    if not profits:
        return {
            "average_one_contract_pnl": None,
            "median_one_contract_pnl": None,
            "maximum_drawdown_one_contract": None,
        }
    equity = peak = maximum_drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    return {
        "average_one_contract_pnl": round(sum(profits) / len(profits), 2),
        "median_one_contract_pnl": round(float(median(profits)), 2),
        "maximum_drawdown_one_contract": round(maximum_drawdown, 2),
    }


def _numeric_factor(value: object) -> float:
    return float("inf") if value == "infinite" else float(value or 0)


def _row_value(row: object, key: str) -> object:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _contract_selection_reasons(samples: list) -> dict[str, int]:
    """Count why a detected setup did not receive an entry option quote."""
    reasons: dict[str, int] = defaultdict(int)
    for row in samples:
        if _row_value(row, "entry_ask") is not None:
            continue
        try:
            metadata = json.loads(str(_row_value(row, "metadata_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        preview = (
            metadata.get("manual_plan", {}).get("contract_preview", {})
            if isinstance(metadata, dict) else {}
        )
        reason = str(preview.get("reason") or "not_recorded").strip().lower()
        reasons[reason] += 1
    return dict(sorted(reasons.items()))


def _contract_selection_message(reasons: dict[str, int]) -> tuple[str, str]:
    """Explain a failed research option screen without calling it quote loss."""
    total = sum(reasons.values())
    if reasons.get('no_expirations_in_window'):
        count = reasons['no_expirations_in_window']
        return (
            f"{count} setup{'s' if count != 1 else ''} found options, but no expiration fit this test's date window.",
            "Test a separate longer-expiration profile with the same entry and exit. Keep its results separate from the original test.",
        )
    if reasons.get('no_listed_expirations'):
        return (
            f"{reasons['no_listed_expirations']} setups received no current expiration listings.",
            "Keep testing the stock setup; verify option availability before starting an option-price experiment.",
        )
    if reasons.get('expiration_data_unavailable'):
        return (
            f"{reasons['expiration_data_unavailable']} setups could not verify option expiration data.",
            "Check the recorded lookup status before changing entry, exit, or expiration rules. A failed lookup is not a strategy loss.",
        )
    if reasons.get("illiquid"):
        return (
            f"{total} setup{'s' if total != 1 else ''} appeared, but the matching options had spreads wider than 8%.",
            "Compare a wider spread limit in research only; do not change the strategy entry yet.",
        )
    if reasons.get("no_chain_data") or reasons.get("no_expirations") or reasons.get("api_error"):
        return (
            f"{total} setup{'s' if total != 1 else ''} appeared; Tradier did not return a usable weekly option chain for at least one attempt.",
            "Retry the same contract lookup on future setups and keep chain failures separate from strategy performance.",
        )
    if reasons.get("filtered"):
        return (
            f"{total} setup{'s' if total != 1 else ''} appeared, but no out-of-the-money option met the $1.50–$10 price and 8% spread rules.",
            "Compare one wider premium or spread rule in research only while keeping the entry and exit unchanged.",
        )
    return (
        f"{total} setup{'s' if total != 1 else ''} appeared, but no complete entry option price was recorded.",
        "Record the exact contract-selection outcome on the next setup before changing the entry or exit.",
    )


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
        **_distribution_summary(profits),
        "mistimed_quotes_ignored": sum(result[1] == "mistimed_quote" for _, result in measured),
    }, dated_profits)


def _without_incomparable_quotes(row: object, *, research_pair: bool) -> dict:
    """Keep setups but blank quotes captured under the wrong contract profile."""
    item = dict(row)
    source = str(item.get("entry_source") or "")
    comparable = (
        source == RESEARCH_CONTRACT_SOURCE
        if research_pair else source != RESEARCH_CONTRACT_SOURCE
    )
    if comparable:
        return item
    for key in (
        "entry_ask", "entry_quote_at", "bid_30", "mark_30_at",
        "bid_60", "mark_60_at", "bid_90", "mark_90_at",
        "bid_120", "mark_120_at",
    ):
        item[key] = None
    return item


def completed_strategy_results(samples, strategy_id, exits, minutes):
    """Exact current-rule exits only; timer comparisons cannot qualify a stop rule."""
    results = []
    for sample in samples:
        if sample["entry_ask"] is None or int(_row_value(sample, "quote_contracts") or 1) != 1:
            continue
        if strategy_id in PROTOCOLS:
            row = exits.get(sample["candidate_id"], {})
            if row.get("protocol") != PROTOCOLS[strategy_id]:
                continue
            profit = net_profit(row)
            start, end = row.get("entry_quote_at"), row.get("decision_at")
            try:
                if not row.get("bid_at") or not end or not 0 <= (timestamp(row["bid_at"]) - timestamp(end)).total_seconds() <= 300:
                    continue
                if row.get("contract_symbol") != _row_value(sample, "entry_contract"):
                    continue
            except (TypeError, ValueError):
                continue
            # Partial exits must use the complete two-contract plan, normalized
            # per contract, not just the remaining runner.
            from strategy_health.context_orb_exit import PREMIUM_PROTOCOLS
            if strategy_id in PREMIUM_PROTOCOLS and profit is not None:
                path = row.get("premium_path") or {}
                if not path.get("quote_count"):
                    continue
                if path.get("partial_bid") is not None:
                    first = net_profit({**row, "bid": path["partial_bid"]})
                    profit = (profit + first) / 2 if first is not None else None
        elif exit_measurement(strategy_id, minutes)["authored_exit_collected"]:
            profit = _quote_profit(sample, minutes)
            start, end = sample["entry_quote_at"], sample[f"mark_{minutes}_at"]
        else:
            continue
        if profit is not None and math.isfinite(profit) and start and end:
            try:
                if timestamp(end) <= timestamp(start):
                    continue
            except (TypeError, ValueError):
                continue
            results.append({"id": sample["candidate_id"], "entry_at": start, "exit_at": end, "pnl": profit})
    return sorted(results, key=lambda row: (timestamp(row["entry_at"]), row["id"]))


def _contract_policy_summaries(
    grouped: dict[tuple[str, str, str], list], *, strategy_id: str,
    ticker: str, exit_minutes: int, sessions: int,
) -> list[dict]:
    """Score each current research contract policy without mixing policies."""
    summaries: list[dict] = []
    for policy in CONTRACT_POLICY_LABELS:
        raw_samples = grouped.get((strategy_id, ticker, policy))
        if not raw_samples:
            continue
        timely = [row for row in raw_samples if candidate_signal_is_timely(row)]
        current, _, _, _ = _current_rule_samples(timely, strategy_id, ticker)
        distinct = _distinct_samples(current, exit_minutes)
        summary, dated_profits = _exit_summary(distinct, exit_minutes)
        result_days = len({day for day, _ in dated_profits})
        older, newer = _chronological_factors(dated_profits)
        comparison_split_date = _chronological_split_date(dated_profits)
        status, explanation = research_status(
            results=summary["option_results"], days=result_days,
            sessions=sessions, factor=summary["profit_factor"],
            median_pnl=summary["median_one_contract_pnl"],
            older_factor=older, newer_factor=newer,
            comparison_split_date=comparison_split_date,
        )
        summaries.append({
            "policy": policy,
            "label": CONTRACT_POLICY_LABELS.get(policy, policy.replace("_", " ").title()),
            "profile_version": RESEARCH_CONTRACT_PROFILE_VERSION,
            "status": status,
            "explanation": explanation,
            "option_results": summary["option_results"],
            "option_result_days": result_days,
            "wins": summary["wins"],
            "win_rate_pct": summary["win_rate_pct"],
            "profit_factor": summary["profit_factor"],
            "net_one_contract_pnl": summary["net_one_contract_pnl"],
            "average_one_contract_pnl": summary["average_one_contract_pnl"],
            "median_one_contract_pnl": summary["median_one_contract_pnl"],
            "maximum_drawdown_one_contract": summary["maximum_drawdown_one_contract"],
            "mistimed_quotes_ignored": summary["mistimed_quotes_ignored"],
            "older_profit_factor": older,
            "newer_profit_factor": newer,
            "comparison_split_date": comparison_split_date,
        })
    return sorted(
        summaries,
        key=lambda item: (
            -int(item["option_results"]),
            -_numeric_factor(item["profit_factor"]),
            item["label"],
        ),
    )


def _current_rule_samples(
    samples: list, strategy_id: str, ticker: str,
) -> tuple[list, int, int, int]:
    """Keep only evidence emitted by the exact currently deployed version."""
    from trading.portfolio_policy import reviewed_strategy_entry_evidence_status

    eligible = []
    rejected = 0
    unscored = 0
    previous_version = 0
    reviewed = REVIEWED_STRATEGIES.get(strategy_id)
    runtime = strategy_details(strategy_id)
    current_version = reviewed.version if reviewed else (runtime.version if runtime else None)
    current_version = evidence_version(strategy_id, current_version)
    for row in samples:
        try:
            metadata = json.loads(str(_row_value(row, "metadata_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        if current_version is not None and str(metadata.get("strategy_version") or "") != current_version:
            previous_version += 1
            continue
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
    return eligible, rejected, unscored, previous_version


def _chronological_factors(dated_profits: list[tuple[str, float]]) -> tuple[object, object]:
    days = sorted({day for day, _ in dated_profits})
    if len(dated_profits) < 20 or len(days) < 8:
        return None, None
    split = min(max(5, int(len(days) * 0.7)), len(days) - 3)
    older_days = set(days[:split])
    older = [profit for day, profit in dated_profits if day in older_days]
    newer = [profit for day, profit in dated_profits if day not in older_days]
    return _factor(older), _factor(newer)


def _chronological_split_date(dated_profits: list[tuple[str, float]]) -> str | None:
    """Name the exact first day of the recent comparison window."""
    days = sorted({day for day, _ in dated_profits})
    if len(dated_profits) < 20 or len(days) < 8:
        return None
    split = min(max(5, int(len(days) * 0.7)), len(days) - 3)
    return days[split]


def research_status(
    *, results: int, days: int, sessions: int, factor: object,
    median_pnl: float | None = None,
    older_factor: object = None, newer_factor: object = None,
    comparison_split_date: str | None = None,
) -> tuple[str, str]:
    numeric = _numeric_factor(factor)
    if results >= 20 and days >= 8 and numeric >= 1.5:
        if median_pnl is not None and median_pnl <= 0:
            return "needs_tuning", "PF is above 1.5, but the typical trade does not make money."
        if newer_factor is not None and _numeric_factor(newer_factor) < 1.5:
            boundary = comparison_split_date or "the comparison date"
            return "needs_tuning", f"It passed before {boundary} but fell below 1.5 from {boundary}."
        return "working", "PF is at least 1.5 across enough days."
    if results >= 20 and numeric < 1.0:
        return "not_working", "This version is losing and needs a change."
    if results >= 10 and numeric < 1.5:
        return "needs_tuning", "PF is below 1.5. Keep the data and tune the rule."
    if results >= 3 and numeric < 1.0:
        return "losing_so_far", "The first results are losing. Do not promote this pair yet."
    if results >= 5 and numeric >= 1.5:
        if median_pnl is not None and median_pnl <= 0:
            return "needs_tuning", "PF is above 1.5, but the typical trade does not make money."
        return "promising", "PF is above 1.5, but there are not enough results yet."
    if results:
        return "collecting", "More results are needed before judging it."
    if sessions >= ENTRY_TUNING_MARKET_DAYS:
        return "needs_tuning", "No setup appeared across enough market days. Test the entry rules."
    return "collecting", "The bot is still collecting market days."


def _diagnosis(
    *, status: str, setups: int, option_results: int, direction_results: int,
    direction_accuracy: float | None, factor: object, older_factor: object,
    newer_factor: object, exit_minutes: int, exit_summaries: list[dict],
    comparison_split_date: str | None = None,
    selection_reasons: dict[str, int] | None = None,
    sessions: int = 0,
) -> tuple[str, str]:
    if status == "working":
        return "ready", "Passed PF 1.5 and the minimum sample checks."
    if setups == 0:
        if sessions >= ENTRY_TUNING_MARKET_DAYS:
            return "entry_tuning", "No setup appeared in 10 market days. Test one entry rule at a time."
        return "no_setups", "No setup yet. Keep watching."
    if option_results == 0 and selection_reasons:
        _, action = _contract_selection_message(selection_reasons)
        return "contract_selection", action
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
            boundary = comparison_split_date or "the comparison date"
            return "unstable", f"Worked before {boundary}, but not from {boundary}. Retest the entry."
    alternatives = [
        summary for summary in exit_summaries
        if summary["minutes"] != exit_minutes and summary["option_results"] >= 10
    ]
    if alternatives:
        best = max(alternatives, key=lambda item: _numeric_factor(item["profit_factor"]))
        if _numeric_factor(best["profit_factor"]) >= 1.5 and _numeric_factor(factor) < 1.5:
            return "exit", f"The {best['minutes']}-minute exit tested better. Validate it on future dates."
    if status == "promising":
        return "more_data", "PF is above 1.5, but the sample is too small. Keep collecting."
    if direction_results >= 10 and direction_accuracy is not None:
        if direction_accuracy < 50:
            return "entry", "The stock moved the wrong way too often. Fix the entry rule."
        if direction_accuracy >= 60 and _numeric_factor(factor) < 1.5:
            return "contract_exit", "The stock direction works, but the option does not. Test contract selection and exit."
    return "entry", "PF is below 1.5. Retest the entry rule before enabling it."


def _improvement_tests(
    *, setups: int, sessions: int, option_results: int, option_result_days: int,
    direction_results: int, direction_accuracy: float | None, factor: object,
    exit_minutes: int, exit_summaries: list[dict], contract_tests: list[dict],
    median_pnl: float | None = None,
    selection_reasons: dict[str, int] | None = None,
) -> list[dict]:
    """Turn measured weaknesses into specific next experiments, never claims."""
    plans: list[dict] = []
    coverage = option_results / setups if setups else 0.0
    if setups == 0:
        remaining = max(0, ENTRY_TUNING_MARKET_DAYS - sessions)
        return [{
            "title": "Build the baseline" if remaining else "Tune the entry rules",
            "evidence": f"0 setups across {sessions} collected market days.",
            "test": (
                f"Collect {remaining} more market day{'s' if remaining != 1 else ''}, then start the entry test."
                if remaining else
                "Run research-only replays one gate at a time: time window, then trend, then volume. Keep production unchanged until one version passes later dates."
            ),
        }]
    if option_results == 0 and selection_reasons:
        evidence, test = _contract_selection_message(selection_reasons)
        plans.append({
            "title": "Setup found; no option matched",
            "evidence": evidence,
            "test": test,
        })
    elif coverage < 0.7:
        plans.append({
            "title": "Complete option pricing first",
            "evidence": f"Only {option_results} of {setups} distinct research plays have a usable ask-to-bid result ({coverage * 100:.0f}%).",
            "test": "Repair or extend quote capture for the same contract before judging entry or exit changes.",
        })
    if (
        option_results >= 5 and _numeric_factor(factor) >= 1.5
        and median_pnl is not None and median_pnl <= 0
    ):
        plans.append({
            "title": "Reduce reliance on a few big wins",
            "evidence": f"PF is {_factor_label(factor)}, but the typical one-contract result is ${median_pnl:,.2f}.",
            "test": "Keep the entry and contract fixed. Compare the current timed exit with one causal dynamic exit, then require positive mean and median on future dates.",
        })
    if direction_results >= 5 and direction_accuracy is not None:
        if direction_accuracy < 50:
            plans.append({
                "title": "Test a stricter entry",
                "evidence": f"The stock moved in the predicted direction only {direction_accuracy:.1f}% of {direction_results} measured setups.",
                "test": "Hold the option and exit constant; replay a 15-minute plus 1-hour direction-agreement gate on later, untouched dates.",
            })
        elif direction_accuracy < 60:
            plans.append({
                "title": "Test a chop filter",
                "evidence": f"Direction accuracy is {direction_accuracy:.1f}% across {direction_results} measured setups.",
                "test": "Hold the exit constant; compare one trend-efficiency or relative-volume threshold and validate it on later dates.",
            })
        elif _numeric_factor(factor) < 1.5:
            plans.append({
                "title": "Keep the entry; test option and exit",
                "evidence": f"Direction accuracy is {direction_accuracy:.1f}%, but option PF is {_factor_label(factor)}.",
                "test": "Do not tighten the signal yet. Compare the recorded contract policies and exit windows using the same setup dates.",
            })
    comparable_exits = [
        row for row in exit_summaries
        if row["minutes"] != exit_minutes and row["option_results"] >= 5
    ]
    if comparable_exits:
        best = max(comparable_exits, key=lambda row: _numeric_factor(row["profit_factor"]))
        if _numeric_factor(best["profit_factor"]) > _numeric_factor(factor):
            plans.append({
                "title": f"Forward-test the {best['minutes']}-minute exit",
                "evidence": f"It produced PF {_factor_label(best['profit_factor'])} over {best['option_results']} recorded results versus PF {_factor_label(factor)} at {exit_minutes} minutes.",
                "test": "Freeze the entry and contract choice, then validate this exit on future dates before changing production.",
            })
    comparable_contracts = [row for row in contract_tests if row["option_results"] >= 5]
    if comparable_contracts:
        best_contract = max(
            comparable_contracts, key=lambda row: _numeric_factor(row["profit_factor"]),
        )
        if _numeric_factor(best_contract["profit_factor"]) > _numeric_factor(factor):
            plans.append({
                "title": f"Forward-test {best_contract['label']}",
                "evidence": f"That contract rule produced PF {_factor_label(best_contract['profit_factor'])} over {best_contract['option_results']} recorded results.",
                "test": "Keep the signal and exit unchanged so the contract rule is the only variable.",
            })
    if not plans:
        remaining_results = max(0, 20 - option_results)
        plans.append({
            "title": "Keep collecting unchanged",
            "evidence": f"This pair has {option_results} priced results across the current exact strategy version.",
            "test": f"Keep the rule fixed while collecting {remaining_results} more completed results. Recommendation progress separately counts non-overlapping tests.",
        })
    return plans[:3]


def _factor_label(value: object) -> str:
    if value == "infinite":
        return "∞"
    return f"{float(value):.2f}" if isinstance(value, (int, float)) else "—"


def build_research_matrix(
    days: int = 90, *, start_date: str | None = None, end_date: str | None = None,
) -> dict:
    from config import get_settings
    from database import get_conn, _now_et
    from scanner.state_io import _read_daily_universe

    days = max(1, min(int(days), 365))
    settings = get_settings()
    account_id = settings.get("active_broker_account_id") or None
    now_et = _now_et()
    try:
        start = date.fromisoformat(start_date) if start_date else (now_et - timedelta(days=days)).date()
        end = date.fromisoformat(end_date) if end_date else now_et.date()
    except ValueError as exc:
        raise ValueError("Research dates must use YYYY-MM-DD.") from exc
    if start > end:
        raise ValueError("Research start date must not be after end date.")
    if (end - start).days > 365:
        raise ValueError("Research date range cannot exceed 365 days.")
    cutoff = datetime.combine(start, time.min, tzinfo=now_et.tzinfo).isoformat()
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=now_et.tzinfo).isoformat()
    candidate_account = (
        "s.broker_account_id = ?" if account_id
        else "(s.broker_account_id IS NULL OR s.broker_account_id = '')"
    )
    candle_account = (
        "broker_account_id = ?" if account_id
        else "(broker_account_id IS NULL OR broker_account_id = '')"
    )
    params: tuple[object, ...] = (cutoff, end_exclusive, account_id) if account_id else (cutoff, end_exclusive)
    with get_conn() as conn:
        authored_exits = load_authored_exits(conn, account_id, cutoff)
        profit_tests = load_profit_tests(conn, account_id, cutoff)
        reference_tests = load_reference_tests(conn, account_id, cutoff)
        expiration_studies = {row['candidate_id']: row for row in load_expiration_studies(conn, account=account_id, cutoff=cutoff, summary_only=True)}
        rows = conn.execute(
            """SELECT s.candidate_id,s.observed_at,s.trigger_bar,s.ticker,s.strategy_id,
                      s.direction,s.metadata_json,
                      s.direction_correct,s.directional_move_pct,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.contract_symbol END) AS entry_contract,
                      COUNT(DISTINCT q.contract_symbol) AS quote_contracts,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.ask END) AS entry_ask,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.observed_at END) AS entry_quote_at,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.source END) AS entry_source,
                      MAX(CASE WHEN q.observation_kind='mark_30m' THEN q.bid END) AS bid_30,
                      MAX(CASE WHEN q.observation_kind='mark_30m' THEN q.observed_at END) AS mark_30_at,
                      MAX(CASE WHEN q.observation_kind='mark_60m' THEN q.bid END) AS bid_60,
                      MAX(CASE WHEN q.observation_kind='mark_60m' THEN q.observed_at END) AS mark_60_at,
                      MAX(CASE WHEN q.observation_kind='mark_90m' THEN q.bid END) AS bid_90,
                      MAX(CASE WHEN q.observation_kind='mark_90m' THEN q.observed_at END) AS mark_90_at,
                      MAX(CASE WHEN q.observation_kind='mark_120m' THEN q.bid END) AS bid_120,
                      MAX(CASE WHEN q.observation_kind='mark_120m' THEN q.observed_at END) AS mark_120_at
               FROM shadow_candidates s
               LEFT JOIN candidate_option_quote_observations q ON q.candidate_id=s.candidate_id
               WHERE s.observed_at >= ? AND s.observed_at < ? AND """ + candidate_account +
            " GROUP BY s.candidate_id ORDER BY s.observed_at",
            params,
        ).fetchall()
        alternative_rows = conn.execute(
            """SELECT s.candidate_id,s.observed_at,s.trigger_bar,s.ticker,s.strategy_id,
                      s.direction,s.metadata_json,a.contract_symbol,
                      MAX(CASE WHEN a.observation_kind='entry' THEN a.ask END) AS entry_ask,
                      MAX(CASE WHEN a.observation_kind='entry' THEN a.observed_at END) AS entry_quote_at,
                      MAX(CASE WHEN a.observation_kind='entry' THEN a.policy_json END) AS policy_json,
                      MAX(CASE WHEN a.observation_kind='entry' THEN a.source END) AS entry_source,
                      MAX(CASE WHEN a.observation_kind='mark_30m' THEN a.bid END) AS bid_30,
                      MAX(CASE WHEN a.observation_kind='mark_30m' THEN a.observed_at END) AS mark_30_at,
                      MAX(CASE WHEN a.observation_kind='mark_60m' THEN a.bid END) AS bid_60,
                      MAX(CASE WHEN a.observation_kind='mark_60m' THEN a.observed_at END) AS mark_60_at,
                      MAX(CASE WHEN a.observation_kind='mark_90m' THEN a.bid END) AS bid_90,
                      MAX(CASE WHEN a.observation_kind='mark_90m' THEN a.observed_at END) AS mark_90_at,
                      MAX(CASE WHEN a.observation_kind='mark_120m' THEN a.bid END) AS bid_120,
                      MAX(CASE WHEN a.observation_kind='mark_120m' THEN a.observed_at END) AS mark_120_at
               FROM shadow_candidates s
               JOIN candidate_contract_alternatives a ON a.candidate_id=s.candidate_id
               WHERE s.observed_at >= ? AND s.observed_at < ? AND """ + candidate_account +
            " GROUP BY s.candidate_id,a.contract_symbol "
            "HAVING entry_source = ? ORDER BY s.observed_at",
            params + (RESEARCH_CONTRACT_SOURCE,),
        ).fetchall()
        candle_params: tuple[object, ...] = (cutoff[:10], end_exclusive[:10], account_id) if account_id else (cutoff[:10], end_exclusive[:10])
        exposure = conn.execute(
            "SELECT ticker,substr(bar_time,1,10) AS evidence_day "
            "FROM scanner_candle_observations WHERE bar_time >= ? AND bar_time < ? AND "
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
    all_evidence_dates = sorted({day for dates in evidence_days.values() for day in dates})
    tickers = set(sessions) | {str(value).upper() for value in settings.get("watchlist", [])}
    tickers |= {str(row["ticker"]).upper() for row in rows}
    catalog_ids = {
        strategy_id for strategy_id in reviewed_strategy_ids()
        if (not REVIEWED_STRATEGIES[strategy_id].observation_only
            or bool(settings.get(REVIEWED_STRATEGIES[strategy_id].setting_key, False)))
    }
    from config.research_order_specs import SPECS as order_specs, execution_id
    catalog_ids -= {sid for sid, spec in order_specs.items() if sid != spec.source}
    runtime_ids = enabled_tested_research_ids(settings)
    strategy_ids = sorted(catalog_ids | runtime_ids)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        grouped[(str(row["strategy_id"]).upper(), str(row["ticker"]).upper())].append(row)
    alternative_grouped: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in alternative_rows:
        row = dict(row)
        try:
            policies = json.loads(str(row["policy_json"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            policies = []
        if not isinstance(policies, list):
            continue
        for policy in policies:
            normalized_policy = str(policy or "").strip()
            if normalized_policy in CONTRACT_POLICY_LABELS:
                alternative_grouped[(
                    str(row["strategy_id"]).upper(),
                    str(row["ticker"]).upper(),
                    normalized_policy,
                )].append(row)

    enabled_by_ticker = {
        ticker: enabled_reviewed_strategy_ids(settings, ticker=ticker)
        for ticker in tickers
    }
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
        strategy_current_results: list[tuple[str, float]] = []
        for ticker in sorted(tickers):
            research_version = evidence_version(strategy_id, rule.version if rule else runtime.version)
            trading_enabled = execution_id(strategy_id, research_version, ticker) in enabled_by_ticker[ticker]
            source_samples = grouped.get((strategy_id, ticker), [])
            # This page summarizes the all-setups research contract policy on
            # EVERY ticker. Native order previews belong to a separate cohort;
            # ticker authorization cannot choose which research prices count.
            research_pair = True
            legacy_option_profiles_ignored = sum(
                1 for row in source_samples
                if _row_value(row, "entry_ask") is not None
                and (
                    str(_row_value(row, "entry_source") or "") == RESEARCH_CONTRACT_SOURCE
                ) != research_pair
            )
            raw_samples = [
                _without_incomparable_quotes(row, research_pair=research_pair)
                for row in source_samples
            ]
            timely_samples = [
                row for row in raw_samples if candidate_signal_is_timely(row)
            ]
            stale_or_replayed = len(raw_samples) - len(timely_samples)
            rule_samples, rule_rejected, rule_unscored, previous_version_rows = _current_rule_samples(
                timely_samples, strategy_id, ticker,
            )
            samples = _distinct_samples(rule_samples, exit_minutes, preferred_source=RESEARCH_CONTRACT_SOURCE)
            # Deduplicate inside each experiment's cohort. A paper candidate
            # with the same trigger must not hide its separate research test.
            profit_samples = _distinct_samples(
                [row for row in rule_samples if row['candidate_id'] in profit_tests], exit_minutes)
            reference_samples = _distinct_samples(
                [row for row in rule_samples if row['candidate_id'] in reference_tests], exit_minutes)
            expiration_samples = _distinct_samples(
                [row for row in rule_samples if row['candidate_id'] in expiration_studies], exit_minutes)
            selection_reasons = _contract_selection_reasons(samples)
            exit_summaries = []
            current_results: list[tuple[str, float]] = []
            current_summary = None
            for window in EXIT_WINDOWS:
                window_samples = _distinct_samples(rule_samples, window, preferred_source=RESEARCH_CONTRACT_SOURCE)
                summary, results = _exit_summary(window_samples, window)
                exit_summaries.append(summary)
                if window == exit_minutes:
                    current_summary, current_results = summary, results
            if current_summary is None:
                current_summary = {
                    "minutes": exit_minutes, "option_results": 0, "wins": 0,
                    "win_rate_pct": None, "profit_factor": None,
                    "net_one_contract_pnl": 0.0,
                    "average_one_contract_pnl": None,
                    "median_one_contract_pnl": None,
                    "maximum_drawdown_one_contract": None,
                    "mistimed_quotes_ignored": 0,
                }
            completed = completed_strategy_results(samples, strategy_id, authored_exits, exit_minutes)
            from strategy_health.premium_research import pair_report
            premium_report = pair_report(samples=samples, completed=completed, settings=settings,
                strategy=strategy_id, ticker=ticker, version=research_version,native_exits=authored_exits)
            recommendation = assess(completed)
            current_summary = {**current_summary, **summarize(completed),
                               **_distribution_summary([row['pnl'] for row in completed])}
            completed_profits = [float(row['pnl']) for row in completed]
            current_summary["gross_profit"] = round(sum(value for value in completed_profits if value > 0), 2)
            current_summary["gross_loss"] = round(abs(sum(value for value in completed_profits if value < 0)), 2)
            current_results = [(str(row['entry_at'])[:10], row['pnl']) for row in completed]
            strategy_current_results.extend(current_results)
            factor = current_summary["profit_factor"]
            option_result_days = len({day for day, _ in current_results})
            older_factor, newer_factor = _chronological_factors(current_results)
            comparison_split_date = _chronological_split_date(current_results)
            status, explanation = research_status(
                results=current_summary["option_results"], days=option_result_days,
                sessions=sessions.get(ticker, 0), factor=factor,
                median_pnl=current_summary["median_one_contract_pnl"],
                older_factor=older_factor, newer_factor=newer_factor,
                comparison_split_date=comparison_split_date,
            )
            if recommendation['qualified']:
                status, explanation = 'working', 'Passed the completed-trade review checks.'
            elif recommendation['promising']:
                status, explanation = 'promising', 'Profitable tests so far; recommendation checks are not complete.'
            elif status in {'working', 'promising'}:
                status, explanation = 'collecting', 'More non-overlapping completed tests are needed.'
            correct = sum(1 for row in samples if row["direction_correct"] == 1)
            measured = sum(1 for row in samples if row["direction_correct"] is not None)
            direction_accuracy = round(correct / measured * 100, 1) if measured else None
            diagnosis, next_action = _diagnosis(
                status=status, setups=len(samples),
                option_results=current_summary["option_results"],
                direction_results=measured, direction_accuracy=direction_accuracy,
                factor=factor, older_factor=older_factor, newer_factor=newer_factor,
                exit_minutes=exit_minutes, exit_summaries=exit_summaries,
                comparison_split_date=comparison_split_date,
                selection_reasons=selection_reasons,
                sessions=sessions.get(ticker, 0),
            )
            contract_tests = _contract_policy_summaries(
                alternative_grouped, strategy_id=strategy_id, ticker=ticker,
                exit_minutes=exit_minutes, sessions=sessions.get(ticker, 0),
            ) if research_pair else []
            improvement_tests = _improvement_tests(
                setups=len(samples), sessions=sessions.get(ticker, 0),
                option_results=current_summary["option_results"],
                option_result_days=option_result_days,
                direction_results=measured, direction_accuracy=direction_accuracy,
                factor=factor,
                median_pnl=current_summary["median_one_contract_pnl"],
                exit_minutes=exit_minutes,
                exit_summaries=exit_summaries, contract_tests=contract_tests,
                selection_reasons=selection_reasons,
            )
            pairs.append({
                "ticker": ticker,
                "recommendation": recommendation,
                "reference_contract_test": reference_summary(reference_samples, reference_tests, strategy_id),
                "expiration_study": expiration_study_summary(expiration_samples, expiration_studies, strategy_id,
                    completed_strategy_results(expiration_samples, strategy_id, authored_exits, exit_minutes)),
                "profit_protection_comparison": profit_test_summary(profit_samples, profit_tests, strategy_id) if strategy_id in PROTOCOL_BY_STRATEGY else None,
                "authored_exit_evidence": authored_summary(samples, authored_exits, PROTOCOLS[strategy_id]) if strategy_id in PROTOCOLS else None,
                "status": status,
                "explanation": explanation,
                "first_data_date": min(evidence_days.get(ticker, []), default=None),
                "last_data_date": max(evidence_days.get(ticker, []), default=None),
                "market_days": sessions.get(ticker, 0),
                "setups": len(samples),
                "raw_observations": len(raw_samples),
                "contract_selection_reasons": selection_reasons,
                "rule_rejected": rule_rejected,
                "rule_unscored": rule_unscored,
                "previous_version_rows": previous_version_rows,
                "stale_or_replayed": stale_or_replayed,
                "option_results": current_summary["option_results"],
                "option_result_days": option_result_days,
                "wins": current_summary["wins"],
                "win_rate_pct": current_summary["win_rate_pct"],
                "profit_factor": factor,
                "net_one_contract_pnl": current_summary["net_one_contract_pnl"],
                "gross_profit": current_summary["gross_profit"],
                "gross_loss": current_summary["gross_loss"],
                "average_one_contract_pnl": current_summary["average_one_contract_pnl"],
                "median_one_contract_pnl": current_summary["median_one_contract_pnl"],
                "maximum_drawdown_one_contract": current_summary["maximum_drawdown_one_contract"],
                "direction_results": measured,
                "direction_accuracy": direction_accuracy,
                "quote_coverage_pct": round(current_summary["option_results"] / len(samples) * 100, 1) if samples else None,
                "mistimed_quotes_ignored": current_summary["mistimed_quotes_ignored"],
                "legacy_option_profiles_ignored": legacy_option_profiles_ignored,
                "older_profit_factor": older_factor,
                "newer_profit_factor": newer_factor,
                "comparison_split_date": comparison_split_date,
                "diagnosis": diagnosis,
                "next_action": next_action,
                "improvement_tests": improvement_tests,
                "exit_comparison": exit_summaries,
                "premium_exit_research": premium_report,
                "contract_tests": contract_tests,
                "leading_contract_test": contract_tests[0] if contract_tests else None,
                "research_contract_profile": (
                    RESEARCH_CONTRACT_PROFILE_VERSION if research_pair else None
                ),
                "tradable": trading_enabled,
            })
        priority = {"working": 0, "promising": 1, "losing_so_far": 2, "needs_tuning": 3, "not_working": 4, "collecting": 5, "no_setups": 6}
        strategy_rows.append({
            "strategy_id": strategy_id,
            "display_name": display_name,
            "version": evidence_version(
                strategy_id, rule.version if rule else runtime.version),
            "backtest": _backtest_display(rule) if rule else {},
            "research_enabled": True,
            "current_evidence": {
                "profit_factor": _factor([profit for _, profit in strategy_current_results]),
                "option_results": len(strategy_current_results),
                "option_result_days": len({day for day, _ in strategy_current_results}),
                "net_one_contract_pnl": round(
                    sum(profit for _, profit in strategy_current_results), 2,
                ),
                "average_one_contract_pnl": (
                    round(sum(profit for _, profit in strategy_current_results) / len(strategy_current_results), 2)
                    if strategy_current_results else None
                ),
                "median_one_contract_pnl": (
                    round(float(median(profit for _, profit in strategy_current_results)), 2)
                    if strategy_current_results else None
                ),
                # Pair rows retain exact chronological order. The aggregate
                # contains date-only keys from many tickers, so an account-wide
                # path drawdown would invent an intraday ordering.
                "maximum_drawdown_one_contract": None,
            },
            "trading_tickers": sorted(rule.tickers) if rule and not rule.observation_only else [],
            "exit_minutes": exit_minutes,
            "exit_measurement": {**exit_measurement(strategy_id, exit_minutes), "pf_label": "Strategy-exit PF"},
            "pairs": sorted(pairs, key=lambda pair: (priority[pair["status"]], pair["ticker"])),
        })
    scan_meta = (_read_daily_universe().get("scan_meta") or {})
    return {
        "days": (end - start).days + 1,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "target_profit_factor": 1.5,
        "collection_started_on": all_evidence_dates[0] if all_evidence_dates else None,
        "collected_market_days": len(all_evidence_dates),
        "recommendation_policy": POLICY,
        "cost_model": f"same-contract entry ask to strategy-exit bid, quotes within {QUOTE_WINDOW_GRACE_MINUTES} minutes of the exit, ${OPTION_SLIPPAGE_PER_SIDE:.2f} adverse slippage per side, ${COMMISSION_PER_CONTRACT:.2f} fee per side; partial-exit plans normalized per contract",
        "account_scoped": bool(account_id),
        "ticker_count": len(tickers),
        "strategy_count": len(strategy_rows),
        "scanner_source": scan_meta.get("source"),
        "scanner_source_size": int(scan_meta.get("source_universe_size") or 0),
        "scanner_shortlist_size": int(scan_meta.get("research_candidates") or 0),
        "scanner_phase": scan_meta.get("phase"),
        "strategies": strategy_rows,
    }
