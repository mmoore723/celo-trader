"""
strategy_health/ai_narrator.py — optional Claude-generated summary of a
strategy health audit, layered on TOP of the free rule-based narrator
(narrator.py). Never required: if config.ANTHROPIC_API_KEY is empty, this
module skips itself and the audit still ships with the rule-based text.

Uses `requests` directly against the Messages API instead of adding the
`anthropic` package as a new dependency — one fewer thing to install on EC2.
"""

from __future__ import annotations

import json
import logging

import requests

from config import ANTHROPIC_API_KEY

logger = logging.getLogger("celo_trader.strategy_health.ai_narrator")

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL   = "claude-sonnet-4-5-20250929"
_TIMEOUT = 30

_SYSTEM_PROMPT = (
    "You are a trading-strategy analyst reviewing one day of a paper-trading "
    "options bot's signal funnel. You are given, per strategy, how many raw "
    "signals it found, how many survived the router's quality gates (ADX, "
    "confidence floor, session bias, conflict veto, etc.), and how many "
    "actually became real trades with what P&L. Write a tight, plain-English "
    "summary (under 150 words) that: (1) calls out the single most actionable "
    "pattern (e.g. one strategy being gated out entirely, or router survivors "
    "not converting to trades), (2) does not repeat every number back verbatim "
    "— synthesize, don't recite, (3) never recommends a code change without "
    "noting it needs an A/B backtest first. No markdown headers, no bullet lists — "
    "plain paragraphs. If the data is too thin to say anything useful, say so briefly."
)


def build_ai_narrative(aggregate: dict) -> "str | None":
    """
    Returns a short Claude-written summary, or None if the API key isn't
    configured or the call fails for any reason (never raises — this is a
    nice-to-have layered on top of the free narrator, not a dependency).
    """
    if not ANTHROPIC_API_KEY:
        logger.info("ai_narrator: ANTHROPIC_API_KEY not set — skipping AI summary.")
        return None

    try:
        payload = {
            "model": _MODEL,
            "max_tokens": 400,
            "system": _SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": (
                    "Here is today's strategy health audit data (JSON):\n\n"
                    + json.dumps(aggregate, indent=2, default=str)
                ),
            }],
        }
        resp = requests.post(
            _API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text.strip() or None
    except Exception as exc:
        # Never let an AI-summary failure break the (free, more important)
        # rule-based audit that already ran successfully.
        logger.warning("ai_narrator: Claude API call failed (non-fatal): %s", exc)
        return None
