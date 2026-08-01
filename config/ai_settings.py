"""
config/ai_settings.py — AI reasoning layer toggles (narration + phase-2
decision support).

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import os

# ── AI reasoning layer (ai_reasoning/) ────────────────────────────────────────
# Phase 1: narration only. Feeds the feature snapshot the bot ALREADY computed
# for an entry/exit to Claude, purely to generate plain-English rationale for
# the THINKING panel/journal. Never gates a trade — narration runs on a
# background thread and its result (or failure) has zero effect on trading
# logic. Off by default; flip on once ANTHROPIC_API_KEY is set and you want
# to see it in action.
AI_REASONING_ENABLED     = os.getenv("AI_REASONING_ENABLED", "false").lower() == "true"
# Haiku, not Sonnet — this fires on every entry AND every exit (dozens/day
# once phase-2 tickers are added), unlike ai_narrator.py's once-daily Sonnet
# call. Plain-English rationale doesn't need frontier reasoning; Sonnet is
# reserved for phase-2 decision support where the stakes are higher.
AI_NARRATION_MODEL       = os.getenv("AI_NARRATION_MODEL", "claude-haiku-4-5-20251001")
# Generous on purpose: narration calls run fire-and-forget on a daemon thread
# (see ai_reasoning/narrator.py) and never block the trading loop, so this
# timeout only bounds how long a stray thread can live, not trade latency.
AI_NARRATION_TIMEOUT_SEC = int(os.getenv("AI_NARRATION_TIMEOUT_SEC", "10"))

# Phase 2 (decision support — veto/narrow an already-approved trade) is now
# built (ai_reasoning/decision_support.py) and, per explicit user decision
# 2026-07-20, turned on for PAPER TRADING ONLY to start building a track
# record before it's ever trusted near live capital. AI_DECISION_SUPPORT_
# ENABLED_LIVE is a SECOND, independent switch that stays hard off — decision
# support only ever runs in paper trading unless BOTH flags are true, so a
# single accidental flag flip can never expose live capital to it. Requires
# ANTHROPIC_API_KEY to be set in .env; if it isn't, this whole layer is a
# silent no-op regardless of this flag (see ai_reasoning/client.py).
AI_DECISION_SUPPORT_ENABLED      = os.getenv("AI_DECISION_SUPPORT_ENABLED", "true").lower() == "true"
AI_DECISION_SUPPORT_ENABLED_LIVE = os.getenv("AI_DECISION_SUPPORT_ENABLED_LIVE", "false").lower() == "true"
# Decision support (phase 2) is SYNCHRONOUS and sits in the entry path
# (unlike narration's fire-and-forget daemon thread), so its timeout bounds
# real trade latency, not just a stray thread's lifetime — kept short.
AI_DECISION_TIMEOUT_SEC = int(os.getenv("AI_DECISION_TIMEOUT_SEC", "4"))
# Sonnet, not Haiku — this is a real quality gate that can veto/narrow a
# live-capital trade (once the flags above are flipped on), unlike phase 1's
# plain-English narration. Worth the extra latency/cost for better judgment.
AI_DECISION_MODEL = os.getenv("AI_DECISION_MODEL", "claude-sonnet-4-5-20250929")
