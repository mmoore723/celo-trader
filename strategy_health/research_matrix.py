"""Plain-language, account-scoped strategy/ticker research results."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from config.market_constants import COMMISSION_PER_CONTRACT
from config.strategy_catalog import (
    REVIEWED_STRATEGIES, reviewed_research_exit_minutes,
    reviewed_strategy_ids,
)
from trading.tested_strategy_research import (
    enabled_tested_research_ids, strategy_details,
)


def _factor(profits: list[float]) -> float | str | None:
    wins = sum(value for value in profits if value > 0)
    losses = abs(sum(value for value in profits if value < 0))
    if not profits:
        return None
    if losses == 0:
        return "infinite" if wins > 0 else None
    return round(wins / losses, 2)


def research_status(*, results: int, days: int, sessions: int, factor: object) -> tuple[str, str]:
    numeric = float("inf") if factor == "infinite" else float(factor or 0)
    if results >= 20 and days >= 8 and numeric >= 1.5:
        return "working", "PF is at least 1.5 across enough days."
    if results >= 20 and numeric < 1.0:
        return "not_working", "This version is losing and needs a change."
    if results >= 10 and numeric < 1.5:
        return "needs_tuning", "PF is below 1.5. Keep the data and tune the rule."
    if results and numeric >= 1.5:
        return "promising", "PF is above 1.5, but there are not enough results yet."
    if results:
        return "collecting", "More results are needed before judging it."
    if sessions >= 20:
        return "no_setups", "The bot watched this ticker but the setup did not appear."
    return "collecting", "The bot is still collecting market days."


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
            """SELECT s.candidate_id,s.observed_at,s.ticker,s.strategy_id,
                      s.direction_correct,s.directional_move_pct,
                      MAX(CASE WHEN q.observation_kind='entry' THEN q.ask END) AS entry_ask,
                      MAX(CASE WHEN q.observation_kind='mark_30m' THEN q.bid END) AS bid_30,
                      MAX(CASE WHEN q.observation_kind='mark_60m' THEN q.bid END) AS bid_60,
                      MAX(CASE WHEN q.observation_kind='mark_90m' THEN q.bid END) AS bid_90
               FROM shadow_candidates s
               LEFT JOIN candidate_option_quote_observations q ON q.candidate_id=s.candidate_id
               WHERE s.observed_at >= ? AND """ + candidate_account +
            " GROUP BY s.candidate_id ORDER BY s.observed_at",
            params,
        ).fetchall()
        candle_params: tuple[object, ...] = (cutoff[:10], account_id) if account_id else (cutoff[:10],)
        exposure = conn.execute(
            "SELECT ticker,COUNT(DISTINCT substr(bar_time,1,10)) AS sessions "
            "FROM scanner_candle_observations WHERE bar_time >= ? AND "
            + candle_account + " GROUP BY ticker",
            candle_params,
        ).fetchall()

    sessions = {str(row["ticker"]).upper(): int(row["sessions"] or 0) for row in exposure}
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
            samples = grouped.get((strategy_id, ticker), [])
            completed_days = {str(row["observed_at"])[:10] for row in samples}
            profits = []
            for row in samples:
                entry = float(row["entry_ask"] or 0)
                bid = float(row[f"bid_{exit_minutes}"] or 0) if exit_minutes in {30, 60, 90} else 0
                if entry > 0 and bid >= 0:
                    profits.append((bid - entry) * 100 - 2 * COMMISSION_PER_CONTRACT)
            factor = _factor(profits)
            status, explanation = research_status(
                results=len(profits), days=len(completed_days),
                sessions=sessions.get(ticker, 0), factor=factor,
            )
            correct = sum(1 for row in samples if row["direction_correct"] == 1)
            measured = sum(1 for row in samples if row["direction_correct"] is not None)
            pairs.append({
                "ticker": ticker,
                "status": status,
                "explanation": explanation,
                "market_days": sessions.get(ticker, 0),
                "setups": len(samples),
                "option_results": len(profits),
                "profit_factor": factor,
                "net_one_contract_pnl": round(sum(profits), 2),
                "direction_accuracy": round(correct / measured * 100, 1) if measured else None,
                "tradable": bool(rule and not rule.observation_only and ticker in rule.tickers),
            })
        priority = {"working": 0, "promising": 1, "needs_tuning": 2, "not_working": 3, "collecting": 4, "no_setups": 5}
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
        "account_scoped": bool(account_id),
        "ticker_count": len(tickers),
        "strategy_count": len(strategy_rows),
        "strategies": strategy_rows,
    }
