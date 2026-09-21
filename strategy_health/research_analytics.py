from __future__ import annotations

from math import inf


ATTENTION = {
    "entry_tuning", "price_data", "contract_selection", "unstable",
    "early_loss", "entry", "exit", "contract_exit",
}


def _pf(gross_profit: float, gross_loss: float, results: int) -> float | str | None:
    if not results:
        return None
    if gross_loss == 0:
        return "infinite" if gross_profit > 0 else None
    return round(gross_profit / gross_loss, 2)


def _status(pair: dict, target: float) -> str:
    factor = pair.get("profit_factor")
    numeric = inf if factor == "infinite" else float(factor or 0)
    if pair.get("option_results", 0) and numeric >= target:
        return "at_goal"
    if pair.get("diagnosis") in ATTENTION:
        return "needs_work"
    return "collecting"


def _totals(rows: list[dict]) -> dict:
    results = sum(int(row.get("option_results") or 0) for row in rows)
    wins = sum(int(row.get("wins") or 0) for row in rows)
    gross_profit = round(sum(float(row.get("gross_profit") or 0) for row in rows), 2)
    gross_loss = round(sum(float(row.get("gross_loss") or 0) for row in rows), 2)
    return {
        "total_triggers": sum(int(row.get("raw_observations") or 0) for row in rows),
        "priced_tests": results,
        "wins": wins,
        "win_rate_pct": round(wins / results * 100, 1) if results else None,
        "profit_factor": _pf(gross_profit, gross_loss, results),
        "net_pnl": round(sum(float(row.get("net_one_contract_pnl") or 0) for row in rows), 2),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def _matches(pair: dict, *, tickers: set[str], statuses: set[str], target: float) -> bool:
    return (not tickers or pair["ticker"] in tickers) and (not statuses or _status(pair, target) in statuses)


def build_analytics(matrix: dict, *, tickers: set[str] | None = None, statuses: set[str] | None = None) -> dict:
    tickers = {ticker.upper() for ticker in (tickers or set())}
    statuses = statuses or set()
    target = float(matrix["target_profit_factor"])
    strategy_rows = []
    ticker_pairs: dict[str, list[dict]] = {}
    selected_pairs = []
    pair_rows = []
    for strategy in matrix["strategies"]:
        pairs = []
        for pair in strategy["pairs"]:
            factor = pair.get("profit_factor")
            state = "at_goal" if factor == "infinite" or isinstance(factor, (int, float)) and factor >= target else "needs_work" if isinstance(factor, (int, float)) and factor < 1 else "collecting"
            if tickers and pair["ticker"] not in tickers or statuses and state not in statuses:
                continue
            pairs.append(pair)
            evidence = pair.get("authored_exit_evidence") or {}
            reasons = evidence.get("reasons") or {}
            recommendation = pair.get("recommendation") or {}
            missing = int(reasons.get("missing_bars", 0))
            late = int(reasons.get("late_entry_quote", 0))
            pair_rows.append({
                "ticker": pair["ticker"], "strategy_id": strategy["strategy_id"],
                "strategy_name": strategy["display_name"], "version": strategy.get("version"),
                **_totals([pair]), "status": state,
                "distinct_plays": int(pair.get("setups") or 0),
                "completed_tests": int(recommendation.get("completed_trades", pair.get("option_results") or 0)),
                "independent_tests": int(recommendation.get("independent_trades") or 0),
                "target_tests": 20,
                "typical_profit": pair.get("median_one_contract_pnl"),
                "active_tests": int(evidence.get("collecting") or 0),
                "tracked_tests": int(evidence.get("tracked") or 0),
                "missing_candles": missing, "late_entry_prices": late,
                "missing_quotes": int(evidence.get("missing_quote") or 0),
                "pending_quotes": int(evidence.get("pending_quote") or 0),
                "target_2r_hits": int(reasons.get("underlying_2r_target", 0)) if evidence else None,
                "health_available": bool(evidence),
            })
        if not pairs:
            continue
        selected_pairs.extend(pairs)
        for pair in pairs:
            ticker_pairs.setdefault(pair["ticker"], []).append(pair)
        totals = _totals(pairs)
        strategy_rows.append({
            "strategy_id": strategy["strategy_id"],
            "strategy_name": strategy["display_name"],
            **totals,
            "status": "at_goal" if totals["profit_factor"] == "infinite" or isinstance(totals["profit_factor"], (int, float)) and totals["profit_factor"] >= target else "needs_work" if any(pair.get("diagnosis") in ATTENTION for pair in pairs) else "testing",
        })
    ticker_rows = [{"ticker": ticker, **_totals(pairs)} for ticker, pairs in ticker_pairs.items()]
    ranked = sorted(ticker_rows, key=lambda row: (row["net_pnl"], row["win_rate_pct"] or -1), reverse=True)
    summary = _totals(selected_pairs)
    return {
        "start_date": matrix.get("start_date"),
        "end_date": matrix.get("end_date"),
        "target_profit_factor": target,
        "summary": {
            **summary,
            "completed_tests": summary["priced_tests"],
            "active_tests": sum(row["active_tests"] for row in pair_rows),
        },
        "pairs": sorted(pair_rows, key=lambda row: (-(inf if row["profit_factor"] == "infinite" else float(row["profit_factor"]) if row["profit_factor"] is not None else -1), row["ticker"], row["strategy_id"])),
        "pipeline": {
            "raw_triggers": summary["total_triggers"],
            "distinct_plays": sum(row["distinct_plays"] for row in pair_rows),
            "priced_results": summary["priced_tests"],
            "completed_tests": sum(row["completed_tests"] for row in pair_rows),
        },
        "data_quality": {
            "tracked_tests": sum(row["tracked_tests"] for row in pair_rows),
            "affected_tests": sum(row["missing_candles"] + row["late_entry_prices"] for row in pair_rows),
            "affected_pct": round(100 * sum(row["missing_candles"] + row["late_entry_prices"] for row in pair_rows) / sum(row["tracked_tests"] for row in pair_rows), 1) if sum(row["tracked_tests"] for row in pair_rows) else None,
            "covered_pairs": sum(row["health_available"] for row in pair_rows),
            "total_pairs": len(pair_rows),
        },
        "strategies": sorted(strategy_rows, key=lambda row: (-((inf if row["profit_factor"] == "infinite" else row["profit_factor"]) or 0), -row["net_pnl"], row["strategy_name"])),
        "tickers": ranked,
        "top_tickers": ranked[:5],
        "bottom_tickers": list(reversed(ranked[-5:])),
        "available_tickers": sorted({pair["ticker"] for strategy in matrix["strategies"] for pair in strategy["pairs"]}),
        "available_strategies": [{"strategy_id": strategy["strategy_id"], "display_name": strategy["display_name"]} for strategy in matrix["strategies"]],
    }


def build_results_page(
    matrix: dict, *, page: int, page_size: int, ticker: str = "",
    strategy_id: str = "", result_filter: str = "results",
) -> dict:
    from copy import deepcopy

    target = float(matrix["target_profit_factor"])
    wanted = ticker.strip().upper()
    rows = []
    counts = {"results": 0, "no_option": 0, "no_setup": 0, "attention": 0, "passing": 0, "all": 0}
    for strategy in matrix["strategies"]:
        for pair in strategy["pairs"]:
            if strategy_id and strategy["strategy_id"] != strategy_id:
                continue
            if wanted and wanted not in pair["ticker"]:
                continue
            measured = int(pair.get("option_results") or 0) > 0
            flags = {
                "results": measured,
                "no_option": not measured and int(pair.get("setups") or 0) > 0,
                "no_setup": int(pair.get("setups") or 0) == 0,
                "attention": pair.get("diagnosis") in ATTENTION,
                "passing": measured and (_status(pair, target) == "at_goal"),
                "all": True,
            }
            for key, enabled in flags.items():
                counts[key] += int(enabled)
            if flags.get(result_filter, flags["results"]):
                rows.append((strategy, pair))
    priority = {"working": 0, "promising": 1, "losing_so_far": 2, "needs_tuning": 3, "not_working": 4, "collecting": 5, "no_setups": 6}
    rows.sort(key=lambda item: (priority.get(item[1]["status"], 99), -int(item[1].get("option_results") or 0), item[0]["display_name"], item[1]["ticker"]))
    total = len(rows)
    start = (page - 1) * page_size
    selected = rows[start:start + page_size]
    by_strategy: dict[str, dict] = {}
    for strategy, pair in selected:
        item = by_strategy.setdefault(strategy["strategy_id"], {key: deepcopy(value) for key, value in strategy.items() if key != "pairs"})
        item.setdefault("pairs", []).append(deepcopy(pair))
    metadata = {key: deepcopy(value) for key, value in matrix.items() if key != "strategies"}
    return {
        **metadata,
        "strategies": list(by_strategy.values()),
        "result_counts": counts,
        "pagination": {"page": page, "page_size": page_size, "total": total, "has_more": start + page_size < total},
        "available_tickers": sorted({pair["ticker"] for strategy in matrix["strategies"] for pair in strategy["pairs"]}),
        "available_strategies": [{"strategy_id": strategy["strategy_id"], "display_name": strategy["display_name"]} for strategy in matrix["strategies"]],
    }
