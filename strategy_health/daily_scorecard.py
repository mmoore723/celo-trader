"""Plain-language session scorecard calculated from immutable evidence."""

from __future__ import annotations

from collections import defaultdict
import json

from strategy_health.golden_replay import replay_event_tape


def _grade(pnl: float) -> tuple[str, str]:
    if pnl > 200: return "A+", "Exceptional positive session"
    if pnl > 100: return "A", "Strong positive session"
    if pnl > 0: return "B", "Positive session"
    if pnl > -50: return "C", "Near break-even session"
    if pnl > -150: return "D", "Losing session"
    return "F", "Large losing session"


def _profit_factor(pnls: list[float]) -> float | str | None:
    gains = sum(value for value in pnls if value > 0)
    losses = abs(sum(value for value in pnls if value < 0))
    if not pnls: return None
    if not losses: return "infinite" if gains else None
    return round(gains / losses, 2)


def _missed_moves(events: list[dict]) -> dict:
    candidates = {e["candidate_id"]: e["payload"] for e in events if e["kind"] == "candidate"}
    quotes: dict[str, dict[str, dict]] = defaultdict(dict)
    for event in events:
        if event["kind"] == "candidate_quote":
            quotes[event["candidate_id"]][event["payload"]["observation_kind"]] = event["payload"]
    horizons = {}
    for mark_name in ("mark_30m", "mark_60m", "mark_90m"):
        returns = []
        for candidate_id, candidate in candidates.items():
            if candidate.get("final_outcome") == "entered": continue
            entry, mark = quotes[candidate_id].get("entry"), quotes[candidate_id].get(mark_name)
            if not entry or not mark or not entry.get("ask") or mark.get("bid") is None: continue
            returns.append((float(mark["bid"]) - float(entry["ask"])) / float(entry["ask"]) * 100)
        horizons[mark_name.replace("mark_", "")] = {
            "measured": len(returns), "profitable": sum(value > 0 for value in returns),
            "avg_executable_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        }
    return horizons


def _exact_missed_order_markout(events: list[dict]) -> dict:
    """Quote-only markout for unfilled orders at each strategy's planned hold.

    This deliberately requires an exact candidate ID, OCC contract symbol,
    recorded entry ask, and recorded exit-horizon bid.  It never invents a
    fill and does not include candidates that never reached an order attempt.
    """
    from config.strategy_catalog import REVIEWED_STRATEGIES

    quotes: dict[tuple[str, str, str], dict] = {}
    for event in events:
        if event["kind"] not in {"candidate_quote", "candidate_contract_quote"}:
            continue
        row = event["payload"]
        key = (
            str(row.get("candidate_id") or ""),
            str(row.get("contract_symbol") or ""),
            str(row.get("observation_kind") or ""),
        )
        # Alternative-contract rows are the authoritative source when the
        # actual order contract differed from the candidate's primary preview.
        if key not in quotes or event["kind"] == "candidate_contract_quote":
            quotes[key] = row

    estimates: list[dict] = []
    for event in events:
        if event["kind"] != "signal":
            continue
        signal = event["payload"]
        if signal.get("outcome") != "blocked" or signal.get("reason_code") != "entry_price_not_reached":
            continue
        try:
            context = json.loads(signal.get("context_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        intent = context.get("order_intent") if isinstance(context, dict) else None
        if not isinstance(intent, dict):
            continue
        candidate_id = str(intent.get("candidate_id") or "")
        contract_symbol = str(intent.get("contract_symbol") or "")
        strategy_id = str(intent.get("strategy_id") or signal.get("strategy_id") or "")
        strategy = REVIEWED_STRATEGIES.get(strategy_id)
        hold_minutes = strategy.exit_minutes if strategy else None
        quantity = int(intent.get("quantity") or context.get("planned_quantity") or 0)
        if not candidate_id or not contract_symbol or hold_minutes not in {30, 60, 90} or quantity < 1:
            continue
        entry = quotes.get((candidate_id, contract_symbol, "entry"))
        mark = quotes.get((candidate_id, contract_symbol, f"mark_{hold_minutes}m"))
        if not entry or not mark or not entry.get("ask") or mark.get("bid") is None:
            continue
        entry_ask = float(entry["ask"])
        mark_bid = float(mark["bid"])
        estimates.append({
            "candidate_id": candidate_id,
            "contract_symbol": contract_symbol,
            "strategy_id": strategy_id,
            "hold_minutes": hold_minutes,
            "quantity": quantity,
            "return_pct": (mark_bid - entry_ask) / entry_ask * 100,
            "pnl_dollars": (mark_bid - entry_ask) * quantity * 100,
        })

    return {
        "measured": len(estimates),
        "profitable": sum(row["pnl_dollars"] > 0 for row in estimates),
        "avg_executable_return_pct": (
            round(sum(row["return_pct"] for row in estimates) / len(estimates), 2)
            if estimates else None
        ),
        "estimated_pnl_dollars": (
            round(sum(row["pnl_dollars"] for row in estimates), 2)
            if estimates else None
        ),
        "contracts": sum(row["quantity"] for row in estimates),
        "basis": (
            "Recorded ask at the unfilled order and recorded bid at that "
            "strategy's reviewed hold; quote estimate only, not a guaranteed fill."
        ),
    }


def build_daily_scorecard(tape: dict) -> dict:
    events = tape["events"]
    exits = [e["payload"] for e in events if e["kind"] == "trade_exit"]
    pnls = [float(row.get("realized_pnl") or 0) for row in exits]
    gains = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    pnl = round(sum(pnls), 2)
    letter, label = _grade(pnl)
    candidates = [e["payload"] for e in events if e["kind"] == "candidate"]
    measured = [row for row in candidates if row.get("direction_correct") is not None]

    attempts: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event["kind"] == "order": attempts[str(event["attempt_id"])].append(event["payload"])
    entry_attempts = [rows for rows in attempts.values() if any(row.get("position_intent") == "buy_to_open" for row in rows)]
    exit_attempts = [rows for rows in attempts.values() if any(row.get("position_intent") == "sell_to_close" for row in rows)]
    filled = lambda rows: any(row.get("event_type") in {"filled", "partial_filled"} for row in rows)
    issues = sum(any(bool(row.get("is_issue")) for row in rows) for rows in attempts.values())
    replay = replay_event_tape(events)
    missed_moves = _missed_moves(events)
    missed_moves["planned_hold"] = _exact_missed_order_markout(events)
    observations = []
    if losses and abs(sum(losses)) > sum(gains): observations.append("Losses outweighed wins; review entry context and exit timing.")
    if entry_attempts and not all(filled(rows) for rows in entry_attempts): observations.append("At least one entry order did not fill.")
    if issues: observations.append(f"Broker lifecycle recorded issues on {issues} order attempt(s).")
    if replay["coverage_pct"] < 100: observations.append("Some decisions or fills are missing linked replay evidence.")
    strategy_replay = replay["strategy_replay"]
    if strategy_replay["strategy_ticker_checks"] and not strategy_replay["complete"]:
        observations.append("Strategy replay is incomplete because an intraminute input was not recorded.")
    if strategy_replay["strategy_ticker_checks"] and not strategy_replay["passed"]:
        observations.append("At least one recorded setup did not match deterministic strategy replay.")
    planned_misses = missed_moves["planned_hold"]
    if planned_misses["measured"]:
        observations.append(
            f"{planned_misses['profitable']} of {planned_misses['measured']} unfilled "
            "orders had positive exact-contract quote markouts at their planned holds; "
            "these are estimates, not broker fills."
        )
    if not observations: observations.append("No execution or evidence exception was detected in this session tape.")
    return {
        "date": tape["date"], "mode": tape["mode"], "account_scoped": tape["account_scoped"],
        "session_result": {"grade": letter, "label": label, "net_pnl": pnl,
                           "basis": "The familiar letter grade is based on this session's realized net P&L only."},
        "trading": {"closed_trades": len(pnls), "wins": len(gains), "losses": len(losses),
                    "win_rate_pct": round(len(gains) / len(pnls) * 100, 1) if pnls else None,
                    "profit_factor": _profit_factor(pnls),
                    "avg_win": round(sum(gains) / len(gains), 2) if gains else None,
                    "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
                    "largest_loss": round(min(losses), 2) if losses else None},
        "decisions": {"candidates": len(candidates), "entered": sum(row.get("final_outcome") == "entered" for row in candidates),
                      "blocked": sum(row.get("final_outcome") == "blocked" for row in candidates),
                      "measured": len(measured), "directional_accuracy_pct": round(sum(bool(row.get("direction_correct")) for row in measured) / len(measured) * 100, 1) if measured else None,
                      "missed_executable_moves": missed_moves},
        "execution": {"entry_attempts": len(entry_attempts), "entry_filled": sum(filled(rows) for rows in entry_attempts),
                      "entry_fill_rate_pct": round(sum(filled(rows) for rows in entry_attempts) / len(entry_attempts) * 100, 1) if entry_attempts else None,
                      "exit_attempts": len(exit_attempts), "exit_filled": sum(filled(rows) for rows in exit_attempts),
                      "exit_fill_rate_pct": round(sum(filled(rows) for rows in exit_attempts) / len(exit_attempts) * 100, 1) if exit_attempts else None,
                      "attempts_with_issues": issues},
        "replay": replay, "observations": observations,
        "launch_readiness": {"status": "not_determined_by_one_day", "note": "Launch readiness requires after-cost results across multiple independent sessions and a chronological holdout."},
    }
