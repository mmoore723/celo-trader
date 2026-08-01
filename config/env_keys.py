"""
config/env_keys.py — Broker API credentials and third-party API keys read
from the environment (.env).

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import os

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER      = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_BASE_URL   = (
    "https://paper-api.alpaca.markets"
    if ALPACA_PAPER else "https://api.alpaca.markets"
)

TRADIER_API_KEY    = os.getenv("TRADIER_API_KEY", "")
TRADIER_BASE_URL   = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")
TRADIER_ACCOUNT_ID = os.getenv("TRADIER_ACCOUNT_ID", "")
POLYGON_API_KEY    = os.getenv("POLYGON_API_KEY", "")

# Optional — used by strategy_health/ai_narrator.py (nightly audit summary)
# AND ai_reasoning/ (per-trade narration + phase-2 decision support, see
# config/ai_settings.py). Empty = every AI feature in the app silently
# skips itself and falls back to its free rule-based equivalent — nothing
# here is ever load-bearing.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
