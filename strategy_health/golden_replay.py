"""Deterministic lifecycle replay checks over the unified event tape."""

from __future__ import annotations

from strategy_health.strategy_replay import replay_strategies


def _coverage(name: str, expected: int, proven: int) -> dict:
    return {
        "name": name, "expected": expected, "proven": proven,
        "coverage_pct": round(proven / expected * 100, 1) if expected else 100.0,
    }


def replay_event_tape(events: list[dict]) -> dict:
    """Prove links between decisions, broker fills, and recorded positions."""
    trades = {e["trade_id"] for e in events if e["kind"].startswith("trade_")}
    entered_signals = [e for e in events if e["kind"] == "signal" and e["payload"].get("outcome") == "entered"]
    entered_candidates = [e for e in events if e["kind"] == "candidate" and e["payload"].get("final_outcome") == "entered"]
    fills = [e for e in events if e["kind"] == "order" and e["payload"].get("event_type") in {"filled", "partial_filled"}]
    exits = [e for e in events if e["kind"] == "trade_exit"]
    exit_quotes = {e["trade_id"] for e in events if e["kind"] == "trade_quote" and e["payload"].get("observation_kind") == "exit"}

    signal_links = sum(bool(e["payload"].get("trade_id") in trades) for e in entered_signals)
    candidate_links = sum(bool(e["payload"].get("linked_trade_id") in trades) for e in entered_candidates)
    fill_links = sum(bool(e.get("trade_id") in trades) for e in fills)
    exit_evidence = sum(e["trade_id"] in exit_quotes for e in exits)
    checks = [
        _coverage("entered signals linked to trades", len(entered_signals), signal_links),
        _coverage("entered candidates linked to trades", len(entered_candidates), candidate_links),
        _coverage("broker fills linked to trades", len(fills), fill_links),
        _coverage("closed trades have exit quotes", len(exits), exit_evidence),
    ]
    expected = sum(c["expected"] for c in checks)
    proven = sum(c["proven"] for c in checks)
    issues = [f"{c['expected'] - c['proven']} missing: {c['name']}" for c in checks if c["proven"] < c["expected"]]
    chronological = all(events[i]["timestamp"] <= events[i + 1]["timestamp"] for i in range(len(events) - 1))
    if not chronological:
        issues.append("event tape is not chronological")
    strategy_replay = replay_strategies(events)
    return {
        "passed": not issues, "chronological": chronological,
        "coverage_pct": round(proven / expected * 100, 1) if expected else 100.0,
        "checks": checks, "issues": issues, "strategy_replay": strategy_replay,
    }
