"""
api/main/bootstrap.py — sys.path setup + early boot side effects (logger,
DB init). MUST be imported first by api/main/__init__.py, before app.py or
any router is imported — app.py and every api.routes.* module transitively
imports root-level bare modules (database, config, trading, strategies,
...) that only resolve once ROOT is on sys.path.

Split out of the old single api/main.py (2026-08-01, file-size cleanup);
preserves the original file's exact top-to-bottom execution order (sys.path
insert -> logger setup -> db init).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure bot modules (trading_logic, config, broker, etc.) are importable
# when running from the project root.
# NOTE: __file__ is now api/main/bootstrap.py — one level deeper than the
# original flat api/main.py — so this needs an extra .parent to still land
# on the repo root (known __file__-nesting-depth bug class from this pass).
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Boot bot modules ──────────────────────────────────────────────────────────
try:
    from logger_config import setup_logging
    setup_logging()
except Exception:
    pass

from database import init_db
init_db()
