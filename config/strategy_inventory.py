"""Display tested history alongside, never inside, the execution allowlist."""
import json
from pathlib import Path

INVENTORY_PATH = Path(__file__).with_name("strategy_research_inventory.json")


def tested_strategy_inventory(settings: dict | None = None):
    try:
        payload = json.loads(INVENTORY_PATH.read_text())
        if not isinstance(payload, dict) or not isinstance(payload.get("strategies"), list):
            raise ValueError("Invalid inventory")
        if not isinstance(payload.get("report_details"), dict) or not isinstance(payload.get("other_studies"), list):
            raise ValueError("Invalid report references")
        for row in payload["strategies"]:
            if not isinstance(row, dict) or not isinstance(row.get("strategy_id"), str) or not isinstance(row.get("display_name"), str):
                raise ValueError("Invalid strategy record")
            if not all(isinstance(row.get(key), list) and all(isinstance(v, str) for v in row[key]) for key in ("tickers", "reports")):
                raise ValueError("Invalid strategy references")
        from trading.tested_strategy_research import public_tested_research_strategies
        runtime = public_tested_research_strategies(settings or {})
        runtime_by_id = {row["strategy_id"]: row for row in runtime}
        for row in payload["strategies"]:
            row.update({
                "research_supported": row["strategy_id"] in runtime_by_id,
                "research_enabled": bool(runtime_by_id.get(row["strategy_id"], {}).get("enabled")),
            })
        payload["runtime_research"] = runtime
        return payload
    except (OSError, ValueError):
        return {"strategies": [], "reports_scanned": 0, "other_studies": [], "report_details": {}, "generated_at": "", "unavailable": True}
