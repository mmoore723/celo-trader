#!/usr/bin/env python3
"""Audit prospective strategy PF from real candidate option quotes.

Repeated scanner rows are collapsed into independent setup episodes before
measurement.  The first priced candidate in each setup is frozen; a later
candidate cannot replace it merely because its follow-up quote exists.  Only
the exact reviewed strategy/ticker scope is eligible. Entry uses that
candidate's recorded ask and exit uses the exact same contract's recorded bid
at the strategy's registered 30/90-minute horizon.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from statistics import mean, median
from typing import Any, Iterable

from config.strategy_catalog import REVIEWED_STRATEGIES
from research.jobs.evaluate_reviewed_strategy_selector import simulate_policy


PF_TARGET = 1.50
MIN_EPISODES = 30
MIN_TRADING_DAYS = 10
DEFAULT_FEE_PER_CONTRACT_PER_SIDE = .12
DEFAULT_SLIPPAGE_PRICE_PER_SIDE = .01
DEFAULT_MONTHLY_SUBSCRIPTION = 10.0
DEFAULT_STARTING_CAPITAL = 5_000.0
MAX_SIGNAL_DELAY_SECONDS_BY_STRATEGY = {
    # Trigger bars store their opening timestamp. Five-minute rules become
    # actionable immediately after that candle closes.
    "V2_SPY_TREND_CONT": 390,
    "V2_SPY_AFTERNOON_FVG": 390,
    # One-minute rules become actionable immediately after that candle closes.
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": 150,
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": 150,
}
DEFAULT_MAX_SIGNAL_DELAY_SECONDS = 390


def _moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _signal_is_timely(row: dict[str, Any]) -> bool:
    """Reject restarted/replayed signals which were no longer actionable."""
    if not row.get("trigger_bar"):
        return False
    observed = _moment(row["observed_at"]).replace(tzinfo=None)
    trigger = _moment(row["trigger_bar"]).replace(tzinfo=None)
    delay = (observed - trigger).total_seconds()
    maximum = MAX_SIGNAL_DELAY_SECONDS_BY_STRATEGY.get(
        str(row.get("strategy_id") or ""), DEFAULT_MAX_SIGNAL_DELAY_SECONDS,
    )
    return 0 <= delay <= maximum


def _factor(values: Iterable[float]) -> float | str | None:
    rows = list(values)
    gains = sum(value for value in rows if value > 0)
    losses = -sum(value for value in rows if value < 0)
    if losses <= 0:
        return "inf" if gains > 0 else None
    return round(gains / losses, 4)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return_pct"]) for row in rows]
    pnl = [float(row["net_pnl_one_contract"]) for row in rows]
    factor = _factor(pnl)
    return {
        "episodes": len(rows),
        "trading_days": len({str(row["observed_at"])[:10] for row in rows}),
        "wins": sum(value > 0 for value in returns),
        "losses": sum(value < 0 for value in returns),
        "win_rate_pct": round(100 * sum(value > 0 for value in returns) / len(returns), 2) if returns else None,
        "average_net_return_pct": round(mean(returns), 4) if returns else None,
        "median_net_return_pct": round(median(returns), 4) if returns else None,
        "net_pnl_one_contract": round(sum(pnl), 2),
        "profit_factor_after_costs": factor,
    }


def _pf_number(value: object) -> float:
    return float("inf") if value == "inf" else float(value or 0)


def _account_replay(
    rows: list[dict[str, Any]], *,
    fee_per_contract_per_side: float,
    slippage_price_per_side: float,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    monthly_subscription: float = DEFAULT_MONTHLY_SUBSCRIPTION,
) -> dict[str, Any]:
    """Route measured episodes through the actual portfolio constraints.

    Per-strategy episodes are independently valid but can still overlap with a
    different strategy on the same ticker.  This replay removes that remaining
    source of PF inflation and applies the production growth-sizing ladder.
    """
    candidates: list[dict[str, Any]] = []
    for row in rows:
        entry_time = _moment(row["observed_at"])
        rule = REVIEWED_STRATEGIES[str(row["strategy_id"])]
        candidates.append({
            **row,
            "entry_time": entry_time.isoformat(),
            "signal_time": entry_time.isoformat(),
            "exit_time": (
                entry_time + timedelta(minutes=int(row["registered_exit_minutes"]))
            ).isoformat(),
            "return_pct": float(row["net_return_pct"]),
            "evidence_grade": rule.evidence_grade,
        })
    simulation = simulate_policy(
        candidates,
        policy="all_affordable",
        starting_capital=starting_capital,
        allocation_fraction=.15,
        max_positions=3,
        per_contract_fee_per_side=fee_per_contract_per_side,
        slippage_price_per_side=slippage_price_per_side,
        monthly_subscription=monthly_subscription,
        sizing_model="production_growth_v1",
    )
    accepted = simulation.pop("accepted")
    skipped = simulation.pop("skipped")
    pnls = [float(row["pnl"]) for row in accepted]
    returns = [
        100 * float(row["pnl"]) / float(row["premium_cost"])
        for row in accepted if float(row.get("premium_cost") or 0) > 0
    ]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    fixed_costs = float(simulation["cost_model"]["subscription_costs"])
    factor_denominator = losses + fixed_costs
    factor: float | str | None = (
        round(gains / factor_denominator, 4)
        if factor_denominator > 0 else
        "inf" if gains > 0 else None
    )
    trading_days = len({str(row["entry_time"])[:10] for row in accepted})
    gates = {
        "at_least_30_account_trades": len(accepted) >= MIN_EPISODES,
        "at_least_10_trading_days": trading_days >= MIN_TRADING_DAYS,
        "positive_average": bool(returns) and mean(returns) > 0,
        "positive_median": bool(returns) and median(returns) > 0,
        "pf_at_least_1_50_after_subscription": _pf_number(factor) >= PF_TARGET,
        # A quote that existed is executable evidence, but it is not proof of
        # the broker fill price or latency. Tradier paper/live orders must
        # supply this final parity evidence.
        "same_broker_order_fill_parity": False,
    }
    return {
        "evidence_class": "tradier_executable_quote_replay_not_order_fills",
        "starting_capital": starting_capital,
        "ending_cash": simulation["ending_cash"],
        "account_return_pct": simulation["account_return_pct"],
        "account_trades": len(accepted),
        "trading_days": trading_days,
        "wins": sum(value > 0 for value in pnls),
        "win_rate_pct": round(100 * sum(value > 0 for value in pnls) / len(pnls), 2) if pnls else None,
        "net_pnl_after_all_costs": round(sum(pnls) - fixed_costs, 2),
        "average_net_return_pct": round(mean(returns), 4) if returns else None,
        "median_net_return_pct": round(median(returns), 4) if returns else None,
        "profit_factor_after_all_costs": factor,
        "cash_cost_basis_max_drawdown_pct": simulation["cost_basis_max_drawdown_pct"],
        "cost_model": simulation["cost_model"],
        "accepted_by_strategy": dict(Counter(str(row["strategy_id"]) for row in accepted)),
        "skip_counts": simulation["skip_counts"],
        "skipped_decisions": [
            {
                "candidate_id": row.get("candidate_id"),
                "observed_at": row.get("observed_at"),
                "ticker": row.get("ticker"),
                "strategy_id": row.get("strategy_id"),
                "skip_reason": row.get("skip_reason"),
            }
            for row in skipped
        ],
        "gates": gates,
        "research_target_met": all(
            value for key, value in gates.items()
            if key != "same_broker_order_fill_parity"
        ),
        "launch_ready": all(gates.values()),
    }


def _setup_groups(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Collapse duplicate writes of the same completed trigger candle."""
    by_identity: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        identity = (
            str(row["ticker"]),
            str(row["strategy_id"]),
            str(row["direction"]),
            str(row.get("trigger_bar") or row["observed_at"]),
        )
        by_identity[identity].append(row)
    return sorted(
        (sorted(rows, key=lambda item: _moment(item["observed_at"])) for rows in by_identity.values()),
        key=lambda rows: _moment(rows[0]["observed_at"]),
    )


def analyze(
    db_path: Path, *,
    fee_per_contract_per_side: float = DEFAULT_FEE_PER_CONTRACT_PER_SIDE,
    slippage_price_per_side: float = DEFAULT_SLIPPAGE_PRICE_PER_SIDE,
) -> dict[str, Any]:
    if fee_per_contract_per_side < 0 or slippage_price_per_side < 0:
        raise ValueError("execution costs cannot be negative")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    candidates = [dict(row) for row in conn.execute(
        "SELECT candidate_id, observed_at, ticker, strategy_id, direction, trigger_bar, "
        "final_outcome, linked_trade_id "
        "FROM shadow_candidates ORDER BY observed_at"
    )]
    quote_rows = conn.execute(
        "SELECT candidate_id, observed_at, observation_kind, contract_symbol, bid, ask, source "
        "FROM candidate_option_quote_observations ORDER BY observed_at"
    ).fetchall()
    conn.close()

    quotes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for quote in quote_rows:
        quotes[str(quote["candidate_id"])][str(quote["observation_kind"])] = dict(quote)

    exclusion_reasons: Counter[str] = Counter()
    eligible_candidates: list[dict[str, Any]] = []
    for row in candidates:
        rule = REVIEWED_STRATEGIES.get(str(row["strategy_id"]))
        if rule is None:
            exclusion_reasons["strategy_not_in_reviewed_catalog"] += 1
        elif rule.exit_minutes is None:
            exclusion_reasons["no_registered_executable_exit"] += 1
        elif str(row["ticker"]).upper() not in rule.tickers:
            exclusion_reasons["ticker_outside_reviewed_scope"] += 1
        elif not _signal_is_timely(row):
            exclusion_reasons["expired_or_replayed_signal"] += 1
        else:
            eligible_candidates.append(row)

    priced_setups: list[dict[str, Any]] = []
    setup_groups = _setup_groups(eligible_candidates)
    no_entry_quote_setups = 0
    for episode in setup_groups:
        # Freeze the first candidate with a real entry quote. Never search for
        # a later candidate based on whether its outcome happens to be present.
        first = next((row for row in episode if "entry" in quotes[str(row["candidate_id"])]), None)
        if first is None:
            no_entry_quote_setups += 1
            continue
        rule = REVIEWED_STRATEGIES[str(first["strategy_id"])]
        candidate_quotes = quotes[str(first["candidate_id"])]
        entry = candidate_quotes["entry"]
        exit_kind = f"mark_{rule.exit_minutes}m"
        exit_quote = candidate_quotes.get(exit_kind)
        base = {
            "candidate_id": first["candidate_id"],
            "observed_at": first["observed_at"],
            "ticker": first["ticker"],
            "strategy_id": first["strategy_id"],
            "direction": first["direction"],
            "trigger_bar": first.get("trigger_bar"),
            "registered_exit_minutes": rule.exit_minutes,
            "episode_candidate_count": len(episode),
            "episode_had_entered_trade": any(row["final_outcome"] == "entered" for row in episode),
            "first_candidate_outcome": first["final_outcome"],
            "linked_trade_id": first.get("linked_trade_id"),
        }
        if exit_quote is None:
            priced_setups.append({**base, "measurement_error": f"missing_{exit_kind}"})
            continue
        if str(entry["contract_symbol"]) != str(exit_quote["contract_symbol"]):
            priced_setups.append({**base, "measurement_error": "contract_mismatch"})
            continue
        ask = float(entry["ask"] or 0)
        bid = float(exit_quote["bid"] or 0)
        if ask <= 0 or bid < 0:
            priced_setups.append({**base, "measurement_error": "invalid_quote"})
            continue
        entry_cost = ask * 100 + fee_per_contract_per_side + slippage_price_per_side * 100
        exit_proceeds = bid * 100 - fee_per_contract_per_side - slippage_price_per_side * 100
        net_return = 100 * (exit_proceeds - entry_cost) / (ask * 100)
        priced_setups.append({
            **base,
            "contract_symbol": entry["contract_symbol"],
            "entry_ask": ask,
            "exit_bid": bid,
            "entry_quote_source": entry["source"],
            "exit_quote_source": exit_quote["source"],
            "net_pnl_one_contract": round(exit_proceeds - entry_cost, 2),
            "net_return_pct": round(net_return, 6),
        })

    # A later setup is not independent while the strategy's earlier selected
    # contract would still be open. Apply this before inspecting whether the
    # later outcome won or lost.
    independent: list[dict[str, Any]] = []
    overlap_skips = 0
    busy_until: dict[tuple[str, str], datetime] = {}
    for row in sorted(priced_setups, key=lambda item: _moment(item["observed_at"])):
        key = (str(row["ticker"]), str(row["strategy_id"]))
        opened_at = _moment(row["observed_at"])
        if opened_at < busy_until.get(key, datetime.min.replace(tzinfo=opened_at.tzinfo)):
            overlap_skips += 1
            continue
        independent.append(row)
        busy_until[key] = opened_at + timedelta(minutes=int(row["registered_exit_minutes"]))

    measured = [row for row in independent if row.get("net_return_pct") is not None]
    unmeasured = Counter(
        str(row.get("measurement_error")) for row in independent
        if row.get("measurement_error")
    )

    by_strategy: dict[str, Any] = {}
    auditable_strategy_ids = sorted(
        strategy_id for strategy_id, rule in REVIEWED_STRATEGIES.items()
        if rule.exit_minutes is not None
    )
    for strategy_id in auditable_strategy_ids:
        rows = [row for row in measured if row["strategy_id"] == strategy_id]
        summary = _summary(rows)
        gates = {
            "at_least_30_independent_episodes": summary["episodes"] >= MIN_EPISODES,
            "at_least_10_trading_days": summary["trading_days"] >= MIN_TRADING_DAYS,
            "positive_average": float(summary["average_net_return_pct"] or 0) > 0,
            "positive_median": float(summary["median_net_return_pct"] or 0) > 0,
            "pf_at_least_1_50": _pf_number(summary["profit_factor_after_costs"]) >= PF_TARGET,
        }
        by_strategy[strategy_id] = {
            **summary,
            "entered_candidate_cohort": _summary([
                row for row in rows if row["episode_had_entered_trade"]
            ]),
            "not_entered_candidate_cohort": _summary([
                row for row in rows if not row["episode_had_entered_trade"]
            ]),
            "gates": gates,
            "passed": all(gates.values()),
            "episodes_detail": rows,
        }

    all_strategy_rows_diagnostic = _summary(measured)
    account_level_replay = _account_replay(
        [
            row for row in measured
            if not REVIEWED_STRATEGIES[str(row["strategy_id"])].observation_only
        ],
        fee_per_contract_per_side=fee_per_contract_per_side,
        slippage_price_per_side=slippage_price_per_side,
    )
    return {
        "purpose": "Prospective, independent-episode strategy PF from real scanner option quotes; research only.",
        "database": str(db_path),
        "measurement": "Reviewed ticker scope only; expired/replayed signals excluded; first priced candidate per stable trigger candle; then one non-overlapping one-contract position per ticker/strategy; PF uses net dollars from recorded ask to exact-contract registered-horizon bid.",
        "quote_sources": dict(Counter(str(row["source"]) for row in quote_rows)),
        "costs": {
            "fee_per_contract_per_side": fee_per_contract_per_side,
            "slippage_price_per_side": slippage_price_per_side,
            "displayed_spread": "Paid by crossing the recorded ask and bid.",
        },
        "promotion_gate": {
            "minimum_independent_episodes": MIN_EPISODES,
            "minimum_trading_days": MIN_TRADING_DAYS,
            "minimum_profit_factor": PF_TARGET,
            "positive_average_and_median_required": True,
        },
        "raw_candidates": len(candidates),
        "eligible_reviewed_scope_candidates": len(eligible_candidates),
        "excluded_candidate_reasons": dict(exclusion_reasons),
        "unique_trigger_setups": len(setup_groups),
        "setups_without_entry_quote": no_entry_quote_setups,
        "priced_setups": len(priced_setups),
        "overlapping_setups_skipped": overlap_skips,
        "independent_episodes": len(independent),
        "measured_episodes": len(measured),
        "unmeasured_episode_reasons": dict(unmeasured),
        "all_strategy_rows_diagnostic_not_account_pf": all_strategy_rows_diagnostic,
        "account_level_replay": account_level_replay,
        "by_strategy": by_strategy,
        "decision": {
            "strategies_passing": [key for key, value in by_strategy.items() if value["passed"]],
            "account_research_target_met": account_level_replay["research_target_met"],
            "account_launch_ready": account_level_replay["launch_ready"],
            "runtime_changed": False,
            "reason": (
                "The account-level Tradier quote replay clears the research PF gate, but quote availability does not prove same-broker order fills. Tradier paper/live fill parity remains required for launch."
                if account_level_replay["research_target_met"] else
                "The account-level Tradier quote replay does not yet clear every sample, time-span, center, and PF research gate."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fee-per-contract-per-side", type=float, default=DEFAULT_FEE_PER_CONTRACT_PER_SIDE)
    parser.add_argument("--slippage-price-per-side", type=float, default=DEFAULT_SLIPPAGE_PRICE_PER_SIDE)
    args = parser.parse_args()
    report = analyze(
        args.database,
        fee_per_contract_per_side=args.fee_per_contract_per_side,
        slippage_price_per_side=args.slippage_price_per_side,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
