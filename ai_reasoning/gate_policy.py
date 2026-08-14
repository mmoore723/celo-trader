"""Promotion policy for AI entry decisions.

An LLM opinion is telemetry until that exact strategy has enough independent,
executable option outcomes and passes a later-date comparison against the same
strategy with the opinion ignored.  Adding a strategy here is therefore a
reviewed production promotion, not an ordinary settings toggle.
"""

from __future__ import annotations


# No strategy has yet met the documented gate-scorecard minimum and passed a
# chronological holdout.  The AI is still called in paper mode so it can build
# the missing approve/veto evidence, but its output cannot alter an order.
AI_DECISION_ENFORCED_STRATEGY_IDS: frozenset[str] = frozenset()


def ai_decision_is_enforced(strategy_id: object) -> bool:
    return str(strategy_id or "").strip().upper() in AI_DECISION_ENFORCED_STRATEGY_IDS


def ai_decision_effect(
    strategy_id: object, action: object, size_multiplier: object, current_contracts: int,
) -> tuple[str, int]:
    """Return an auditable effect without ever increasing position size."""
    normalized = str(action or "approve").strip().lower()
    contracts = max(0, int(current_contracts))
    if normalized not in {"veto", "reduce_size"}:
        return "approve", contracts
    if not ai_decision_is_enforced(strategy_id):
        return "observe", contracts
    if normalized == "veto":
        return "veto", 0
    try:
        multiplier = max(0.0, min(float(size_multiplier), 1.0))
    except (TypeError, ValueError):
        multiplier = 1.0
    resized = int(contracts * multiplier)
    return ("veto", 0) if resized < 1 else ("reduce_size", resized)
