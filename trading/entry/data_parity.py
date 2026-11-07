"""Live-entry evidence-source guard. Never grants order permission."""
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def classify_source(evidence):
    """Only classify the current artifact's explicit primary source."""
    market = evidence.get("market_data")
    source = market.get("source") if isinstance(market, dict) else None
    if not isinstance(source, str) or not source.strip():
        return "unknown", "unknown"
    normalized = source.lower()
    if "opra" in normalized or "consolidated" in normalized or "sip" in normalized.split():
        return "consolidated", source
    if "iex" in normalized.split():
        return "iex", source
    return "unknown", source


@lru_cache(maxsize=256)
def evidence_source(strategy_id):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule = REVIEWED_STRATEGIES.get(strategy_id)
    if rule is None:
        return "unknown", "unknown"
    try:
        evidence = json.loads((ROOT / rule.evidence_artifact).read_text())
        if (evidence.get("strategy_id") != rule.strategy_id
                or evidence.get("strategy_version") != rule.version):
            return "unknown", "unknown"
        return classify_source(evidence)
    except (OSError, ValueError, TypeError, AttributeError):
        return "unknown", "unknown"


def live_data_refusal(strategy_id, settings):
    """Return a reason for refusal, or None. Paper behavior is unchanged.

    This is the audit's plan-level prerequisite, not proof of actual feed
    parity. OPRA describes options, not the underlying stock-bar feed.
    """
    if settings.get("paper_trading", True) is True:
        return None
    category, source = evidence_source(strategy_id)
    if category == "unknown":
        return (f"Live entry refused: {strategy_id} has an unknown research data "
                "source for its current evidence version. Verify the source first.")
    if category == "consolidated" and settings.get("alpaca_data_plan", "free") != "premium":
        return (f"Live entry refused: {strategy_id} research used {source}; "
                "the required alpaca_data_plan=premium is not configured.")
    return None
