"""Load completed same-contract candidate observations across account DBs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from config.strategy_catalog import REVIEWED_STRATEGIES


def load_completed_observations(db_paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in db_paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        try:
            available = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {"shadow_candidates", "candidate_option_quote_observations"}.issubset(available):
                continue
            query = """SELECT s.candidate_id,s.observed_at,s.ticker,s.strategy_id,s.metadata_json,
                       e.contract_symbol,e.bid AS entry_bid,e.ask AS entry_ask,
                       x.bid AS exit_bid,x.observation_kind AS exit_kind
                       FROM shadow_candidates s
                       JOIN candidate_option_quote_observations e
                         ON e.candidate_id=s.candidate_id AND e.observation_kind='entry'
                       JOIN candidate_option_quote_observations x ON x.candidate_id=s.candidate_id
                       WHERE x.observation_kind IN ('mark_30m','mark_60m','mark_90m')"""
            for source in conn.execute(query):
                rule = REVIEWED_STRATEGIES.get(str(source["strategy_id"]).upper())
                expected = f"mark_{rule.exit_minutes}m" if rule and rule.exit_minutes else None
                if source["exit_kind"] != expected:
                    continue
                try:
                    metadata = json.loads(source["metadata_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    metadata = {}
                rows.append({**dict(source), "strategy_version": metadata.get("strategy_version")})
        finally:
            conn.close()
    return rows
