"""Nightly, read-only strategy/ticker evidence qualification."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config.atomic_files import atomic_write_json
from config.paths import BASE_DIR
from config.strategy_catalog import REVIEWED_STRATEGIES
from config.strategy_ticker_recommendations import publish_qualified_recommendation
from strategy_health.ticker_qualification import load_completed_observations, qualify_pair

REPORT_PATH = BASE_DIR / "data" / "strategy_ticker_qualification_latest.json"


def _account_database_paths() -> list[Path]:
    root = BASE_DIR / "user_data"
    return sorted({*root.glob("*/trades_paper.db"), *root.glob("*/trades_live.db")}) if root.exists() else []


def run_ticker_qualification() -> dict:
    """Evaluate every observed reviewed pair without changing user consent."""
    raw = load_completed_observations(_account_database_paths())
    pairs = sorted({
        (str(row.get("strategy_id") or "").upper(), str(row.get("ticker") or "").upper())
        for row in raw if row.get("strategy_id") and row.get("ticker")
    })
    results, published = [], []
    for strategy_id, ticker in pairs:
        if strategy_id not in REVIEWED_STRATEGIES:
            continue
        result = qualify_pair(strategy_id, ticker, raw)
        results.append(result)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_count": len(_account_database_paths()),
        "raw_completed_rows": len(raw),
        "results": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(REPORT_PATH, payload)
    artifact = str(REPORT_PATH.relative_to(BASE_DIR))
    for result in results:
        rule = REVIEWED_STRATEGIES[result["strategy_id"]]
        # Existing catalog scope is already governed by its reviewed artifact;
        # only newly discovered ticker mappings need a consent recommendation.
        if result.get("decision") == "qualified" and result["ticker"] not in rule.tickers:
            published.append(publish_qualified_recommendation(result, evidence_artifact=artifact))
    payload["published_recommendations"] = published
    atomic_write_json(REPORT_PATH, payload)
    return payload
