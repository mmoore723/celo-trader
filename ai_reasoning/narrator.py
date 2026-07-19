"""
ai_reasoning/narrator.py — phase 1 of the AI reasoning layer: narration only.

Fires once per actual entry and once per actual exit — never on idle scan
ticks, matching the cost discipline strategy_audit_log.py already uses for
its rule-based narration. Builds a prompt from the already-computed feature
snapshot (see feature_snapshot.py) and asks Claude for a short plain-English
rationale. The result is written through database.log_event() so it shows
up in the THINKING panel/journal exactly like every other bot narration,
and the full prompt/response (or the failure reason) is always persisted to
ai_reasoning_log — this call ran, whether or not it produced usable text.

Hard rule: narration NEVER affects trading logic. Every call runs on a
daemon thread — same pattern trading/loop.py already uses for the nightly
strategy_health audit — so a slow or failed Claude call can never delay the
next tick of the synchronous trading loop. If AI_REASONING_ENABLED is off or
ANTHROPIC_API_KEY is unset, narrate_entry()/narrate_exit() no-op immediately
without spawning a thread — safe to call unconditionally from entry.py and
position_manager.py.
"""

from __future__ import annotations

import json
import logging
import threading

from config import (
    AI_REASONING_ENABLED, AI_NARRATION_MODEL, AI_NARRATION_TIMEOUT_SEC,
    ANTHROPIC_API_KEY,
)
from ai_reasoning.client import call_claude
from ai_reasoning.feature_snapshot import build_entry_snapshot, build_exit_snapshot

logger = logging.getLogger("celo_trader.ai_reasoning.narrator")

_MAX_TOKENS = 220   # short rationale only — this is narration, not analysis

_ENTRY_SYSTEM_PROMPT = (
    "You are narrating ONE options trade entry for a day-trading bot's live "
    "journal. You are given the strategy that fired, its confidence score, "
    "the contract chosen, and the stop/target levels the bot's deterministic "
    "risk engine already calculated. Write 2-3 plain-English sentences a "
    "trader would want to read in their journal: WHY this setup qualified "
    "and WHAT the plan is. Do not recommend changes, do not second-guess the "
    "trade, do not use markdown. You are explaining a decision that has "
    "ALREADY been made and already executed — not evaluating whether it was "
    "correct."
)

_EXIT_SYSTEM_PROMPT = (
    "You are narrating ONE options trade exit for a day-trading bot's live "
    "journal. You are given the exit reason the bot's deterministic exit "
    "engine already chose, plus the multi-timeframe signals (RSI, MACD, ADX, "
    "EMA alignment, 1-hour trend bias, 15-min swing proximity) that fed into "
    "that decision. Write 2-3 plain-English sentences explaining WHY this "
    "exit fired now. Do not recommend changes, do not second-guess the exit, "
    "do not use markdown. You are explaining a decision that has ALREADY "
    "been made and already executed — not evaluating whether it was correct."
)


def narrate_entry(**kwargs) -> None:
    """
    Fire-and-forget entry narration. Accepts the same keyword arguments as
    feature_snapshot.build_entry_snapshot(). No-ops immediately (no thread
    spawned, zero added latency) if the feature is off.
    """
    if not (AI_REASONING_ENABLED and ANTHROPIC_API_KEY):
        return
    try:
        snapshot = build_entry_snapshot(**kwargs)
    except Exception as exc:
        # A bad snapshot must never take down the trade that already happened.
        logger.warning("narrate_entry: snapshot build failed (non-fatal): %s", exc)
        return
    threading.Thread(
        target=_do_narrate, args=("entry_narration", snapshot, _ENTRY_SYSTEM_PROMPT),
        daemon=True, name="ai-narrator-entry",
    ).start()


def narrate_exit(**kwargs) -> None:
    """
    Fire-and-forget exit narration. Accepts the same keyword arguments as
    feature_snapshot.build_exit_snapshot(). No-ops immediately if the
    feature is off.
    """
    if not (AI_REASONING_ENABLED and ANTHROPIC_API_KEY):
        return
    try:
        snapshot = build_exit_snapshot(**kwargs)
    except Exception as exc:
        logger.warning("narrate_exit: snapshot build failed (non-fatal): %s", exc)
        return
    threading.Thread(
        target=_do_narrate, args=("exit_narration", snapshot, _EXIT_SYSTEM_PROMPT),
        daemon=True, name="ai-narrator-exit",
    ).start()


def _do_narrate(event_type: str, snapshot: dict, system_prompt: str) -> None:
    """
    Runs on the daemon thread spawned above — never on the trading loop's
    thread. Imports database.* lazily (same reason trading/entry.py and
    position_manager.py already do it): avoids import-order issues at
    module load time, since database.py and this package can end up in each
    other's import chain depending on load order.
    """
    from database import log_event, log_ai_reasoning

    user_prompt = f"Trade event data (JSON):\n\n{json.dumps(snapshot, indent=2, default=str)}"

    result = call_claude(
        system_prompt = system_prompt,
        user_prompt    = user_prompt,
        model          = AI_NARRATION_MODEL,
        max_tokens     = _MAX_TOKENS,
        timeout_sec    = AI_NARRATION_TIMEOUT_SEC,
    )

    ticker   = snapshot.get("ticker", "?")
    trade_id = snapshot.get("trade_id")

    # Always logged — success, failure, or timeout — so the replay trail the
    # user asked for is complete, not just a highlight reel of what worked.
    log_ai_reasoning(
        event_type       = event_type,
        ticker           = ticker,
        feature_snapshot = snapshot,
        prompt           = system_prompt + "\n\n" + user_prompt,
        response_text    = result.text,
        latency_ms       = result.latency_ms,
        model            = result.model,
        error            = result.error,
        trade_id         = trade_id,
    )

    if result.text:
        log_event("INFO", "ai_reasoning", f"🧠 [{ticker}] {result.text}")
    else:
        # A failed/skipped narration is never worth surfacing in the THINKING
        # panel — it's a nice-to-have layer on top of the rule-based
        # narration that already ran (strategy_audit_log.py / the post-trade
        # recap in position_manager.py), not a dependency. Debug-log only.
        logger.debug(
            "ai_reasoning.narrator: %s skipped for %s (%s)",
            event_type, ticker, result.error,
        )
