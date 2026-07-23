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

# 2026-07-20: weekly rollup gets a DIFFERENT job than the daily narrator.
# Daily just summarizes one day's funnel; weekly is explicitly asked to
# answer "should I change a risk setting or modify a strategy" with a
# specific, testable recommendation — the gap a user flagged directly:
# generic summaries weren't answering that question. Still bound by the same
# hard rule as every other AI output in this codebase: it can point at a
# specific number and suggest a specific test, never claim a change is safe
# to ship without one.
_WEEKLY_SYSTEM_PROMPT = (
    "You are a trading-strategy analyst reviewing ONE WEEK of a paper-trading "
    "options bot's real performance — not a backtest, actual executed trades. "
    "You are given, per strategy: signal-funnel totals (raw signals, router "
    "survivors, actual trades) summed across the week's daily audits, AND "
    "real trade risk-math (win rate, avg win/loss, realized win:loss ratio, "
    "exit-reason mix) computed directly from closed trades. Your job is "
    "different from a daily summary: identify the SINGLE most actionable, "
    "specific, testable change worth considering — e.g. 'MID_BRK's exit mix "
    "is 80% momentum_dead_exit with small losses; worth checking if the RVOL "
    "threshold is too tight' or 'AFT_REV n=6 this week, still too thin to "
    "read.' Rules, no exceptions: (1) name a SPECIFIC strategy and a SPECIFIC "
    "number from the data, never a vague generality like 'monitor closely', "
    "(2) ALWAYS state that any change needs an A/B backtest before shipping — "
    "never imply a change is safe to apply directly, (3) if every strategy's "
    "sample size is too thin (under ~15 trades) to say anything statistically "
    "meaningful, say exactly that instead of inventing a pattern, (4) under "
    "200 words, plain paragraphs, no markdown headers or bullet lists."
)


def _call_claude(system_prompt: str, aggregate: dict, user_intro: str) -> tuple["str | None", "str | None", "int | None", str]:
    """Shared call path for both narrators. Returns (text, error, latency_ms, prompt_used)."""
    import time
    prompt_text = system_prompt + "\n\n" + user_intro + "\n\n" + json.dumps(aggregate, indent=2, default=str)
    if not ANTHROPIC_API_KEY:
        return None, "ANTHROPIC_API_KEY not set", None, prompt_text

    _t0 = time.monotonic()
    try:
        payload = {
            "model": _MODEL,
            "max_tokens": 400,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_intro + "\n\n" + json.dumps(aggregate, indent=2, default=str)}],
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
        latency_ms = int((time.monotonic() - _t0) * 1000)
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return (text.strip() or None), None, latency_ms, prompt_text
    except Exception as exc:
        latency_ms = int((time.monotonic() - _t0) * 1000)
        return None, str(exc), latency_ms, prompt_text


def build_ai_narrative(aggregate: dict) -> "str | None":
    """
    Returns a short Claude-written summary, or None if the API key isn't
    configured or the call fails for any reason (never raises — this is a
    nice-to-have layered on top of the free narrator, not a dependency).
    Logged to ai_reasoning_log (event_type='daily_audit_summary') either way
    so it shows up in the AI Reasoning Log page like every other AI call.
    """
    text, error, latency_ms, prompt = _call_claude(
        _SYSTEM_PROMPT, aggregate, "Here is today's strategy health audit data (JSON):"
    )
    if error and error != "ANTHROPIC_API_KEY not set":
        logger.warning("ai_narrator: Claude API call failed (non-fatal): %s", error)
    _log(event_type="daily_audit_summary", aggregate=aggregate, prompt=prompt,
         response_text=text, latency_ms=latency_ms, error=error)
    return text


def build_weekly_ai_narrative(aggregate: dict) -> "str | None":
    """
    Weekly counterpart to build_ai_narrative — same fail-open, never-raises
    contract, different (more specific, recommendation-oriented) prompt.
    Logged as event_type='weekly_audit_summary'.
    """
    text, error, latency_ms, prompt = _call_claude(
        _WEEKLY_SYSTEM_PROMPT, aggregate, "Here is this week's rolled-up strategy performance data (JSON):"
    )
    if error and error != "ANTHROPIC_API_KEY not set":
        logger.warning("ai_narrator: weekly Claude API call failed (non-fatal): %s", error)
    _log(event_type="weekly_audit_summary", aggregate=aggregate, prompt=prompt,
         response_text=text, latency_ms=latency_ms, error=error)
    return text


def _log(event_type: str, aggregate: dict, prompt: str, response_text: "str | None",
         latency_ms: "int | None", error: "str | None") -> None:
    """Persist to ai_reasoning_log so this shows up in the AI Reasoning Log
    page — previously these calls weren't logged at all, a transparency gap
    flagged directly by the user. Never raises (same discipline as every
    other logger.warning call in this module)."""
    try:
        from database import log_ai_reasoning
        log_ai_reasoning(
            event_type=event_type, ticker="ALL", feature_snapshot=aggregate,
            prompt=prompt, response_text=response_text, latency_ms=latency_ms,
            model=_MODEL, error=error, applied=False,
        )
    except Exception as exc:
        logger.warning("ai_narrator: failed to log to ai_reasoning_log (non-fatal): %s", exc)
