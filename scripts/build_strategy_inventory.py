"""Publish a display-only inventory from saved research, never import strategies.

Run after research jobs: python scripts/build_strategy_inventory.py
Only IDs, ticker coverage and report references are exported. Different tests'
PFs are not combined into a misleading single 'best' strategy PF.
"""
import ast
import json
from pathlib import Path
import re
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,100}$")


def identifier(value):
    return value.upper() if isinstance(value, str) and SID.fullmatch(value) else None


def title(value):
    acronyms = {"ORB", "VWAP", "RSI", "MACD", "EMA", "ATR", "ADX", "CMF", "NR7", "KER", "QQQ", "SPY", "TSLA", "AMZN", "FVG", "BOS", "MSS"}
    return " ".join(word if word in acronyms else word.title() for word in value.upper().replace("_", " ").split())


def walk(value, known, found, inherited=None, ticker=None):
    if isinstance(value, list):
        for item in value:
            walk(item, known, found, inherited, ticker)
    elif isinstance(value, dict):
        symbol = value.get("ticker", ticker)
        sid = identifier(value.get("strategy_id")) or identifier(value.get("strategy")) or inherited
        # Uppercase study IDs also identify standalone screens. Lowercase study
        # names such as 'contract_selection_matrix' are not strategy IDs.
        study = value.get("study")
        if not sid and isinstance(study, str) and study.isupper():
            sid = identifier(study)
        if sid:
            found.setdefault(sid, set())
            if isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", symbol):
                found[sid].add(symbol)
        for key, item in value.items():
            key_sid = identifier(key) if key.upper() in known or key.startswith(("V2_", "CTX_")) and SID.fullmatch(key) else sid
            if key in {"tickers", "symbols"} and isinstance(item, dict):
                for name, details in item.items():
                    walk(details, known, found, key_sid, name)
            else:
                walk(item, known, found, key_sid, symbol)
            if key_sid and key_sid != sid:
                found.setdefault(key_sid, set())


def build(root=ROOT):
    known = set()
    for path in (root / "research/engine").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                targets = [getattr(target, "id", "") for target in node.targets]
                if any(t.lower() in {"strategy_id", "sid"} for t in targets) and SID.fullmatch(node.value.value):
                    known.add(node.value.value)
    reports, errors, details = [], [], {}
    for directory in ("research/reports", "reports"):
        for path in sorted((root / directory).rglob("*.json")):
            try:
                payload = json.loads(path.read_text())
                found = {}
                walk(payload, known, found)
                known.update(found)
                reports.append((path, found))
                source = payload if isinstance(payload, dict) else {}
                relative = str(path.relative_to(root))
                invalid = source.get("valid") is False or "invalid" in path.name or bool(source.get("superseded_by"))
                details[relative] = {
                    "title": title(path.stem),
                    "purpose": source.get("purpose", "") if isinstance(source.get("purpose", ""), str) else "",
                    "decision": source.get("decision", "") if isinstance(source.get("decision", ""), str) else "",
                    "status": "invalid_or_superseded" if invalid else "incomplete" if source.get("complete") is False else "saved_study",
                }
            except (OSError, ValueError) as exc:
                errors.append({"report": str(path.relative_to(root)), "error": type(exc).__name__})
    rows = {}
    for path, found in reports:
        for sid, tickers in found.items():
            row = rows.setdefault(sid, {"strategy_id": sid, "tickers": set(), "reports": []})
            row["tickers"].update(tickers)
            row["reports"].append(str(path.relative_to(root)))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports_scanned": len(reports), "unreadable_reports": errors,
        "report_details": details,
        # Every saved report remains discoverable, including old schemas without
        # an explicit strategy ID. Never invent an ID or silently omit a study.
        "other_studies": [str(path.relative_to(root)) for path, found in reports if not found],
        "strategies": [{**row, "tickers": sorted(row["tickers"]),
                        "display_name": title(sid),
                        "report_count": len(row["reports"])} for sid, row in sorted(rows.items())],
    }


if __name__ == "__main__":
    payload = build()
    output = ROOT / "config/strategy_research_inventory.json"
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"strategies": len(payload["strategies"]), "reports_scanned": payload["reports_scanned"],
                      "unreadable_reports": payload["unreadable_reports"]}))
