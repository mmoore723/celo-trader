"""
ai_reasoning/client.py — thin Claude Messages API caller, shared by every
module in this package.

Modeled directly on strategy_health/ai_narrator.py's existing pattern: raw
`requests` call (no `anthropic` SDK dependency — one less thing to install
on EC2), hard timeout, never raises. Kept as one shared function instead of
copy-pasting that pattern into narrator.py and (later) decision_support.py
so there's exactly one place that owns retry/timeout/error-handling
behavior for this whole layer.

Nothing in this module ever raises. Every failure mode (missing API key,
timeout, network error, malformed response) returns a CallResult with
`error` set instead of an exception. Callers decide what "failure" means
for their own use case — narration just skips logging a rationale;
decision support (phase 2) fails open to "approve" the trade.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from config import ANTHROPIC_API_KEY

logger = logging.getLogger("celo_trader.ai_reasoning.client")

_API_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class CallResult:
    text:       Optional[str]   # model's text output, or None on any failure
    latency_ms: Optional[int]
    model:      str
    error:      Optional[str]   # None on success, else a short failure reason


def call_claude(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    timeout_sec: float,
) -> CallResult:
    """
    Single-attempt Claude Messages API call — no retries. A retry would
    double the worst-case latency for zero benefit here: every caller in
    this package already fails open (narration just skips itself; decision
    support defaults to "approve"), so a second attempt buys nothing but
    risk of the call being even later.
    """
    if not ANTHROPIC_API_KEY:
        return CallResult(text=None, latency_ms=None, model=model,
                           error="ANTHROPIC_API_KEY not set")

    _t0 = time.monotonic()
    try:
        resp = requests.post(
            _API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=timeout_sec,
        )
        _latency_ms = int((time.monotonic() - _t0) * 1000)
        resp.raise_for_status()

        data   = resp.json()
        blocks = data.get("content", [])
        text   = "".join(
            b.get("text", "") for b in blocks if b.get("type") == "text"
        ).strip()

        if not text:
            return CallResult(text=None, latency_ms=_latency_ms, model=model,
                               error="empty response from API")
        return CallResult(text=text, latency_ms=_latency_ms, model=model, error=None)

    except requests.exceptions.Timeout:
        _latency_ms = int((time.monotonic() - _t0) * 1000)
        logger.warning("ai_reasoning.client: Claude call timed out after %.1fs", timeout_sec)
        return CallResult(text=None, latency_ms=_latency_ms, model=model, error="timeout")

    except Exception as exc:
        _latency_ms = int((time.monotonic() - _t0) * 1000)
        logger.warning("ai_reasoning.client: Claude call failed (non-fatal): %s", exc)
        return CallResult(text=None, latency_ms=_latency_ms, model=model, error=str(exc))
