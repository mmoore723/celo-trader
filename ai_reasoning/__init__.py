"""
ai_reasoning — LLM reasoning layer on top of the bot's deterministic
entry/exit logic.

Two phases, built and approved one at a time:

  Phase 1 (this package, as of 2026-07-18) — narration only. Feeds the
  feature snapshot the deterministic system already computed for an entry
  or exit to Claude, purely to generate plain-English rationale for the
  THINKING panel/journal. Never gates a trade, never runs on the trading
  loop's own thread — see narrator.py's docstring for the fail-open design.

  Phase 2 (not built yet, needs separate approval) — decision support. The
  LLM may narrow (reduce size) or veto a trade the deterministic system
  already approved; it can never originate direction or pick a contract.
  Hard timeout, fails open to "approve" on any error, gated behind
  config.AI_DECISION_SUPPORT_ENABLED (and a second, independent
  config.AI_DECISION_SUPPORT_ENABLED_LIVE before it can touch a live-money
  trade — paper trading only otherwise).

Modules:
  client.py           — shared, raw `requests`-based Claude Messages API
                         caller. No `anthropic` SDK dependency, matching the
                         existing strategy_health/ai_narrator.py pattern.
  feature_snapshot.py — pure packaging of already-computed values into a
                         JSON-safe dict. No new indicator math lives here.
  narrator.py          — phase 1: narrate_entry() / narrate_exit().

Every module in this package is designed so that config.ANTHROPIC_API_KEY
being unset, or config.AI_REASONING_ENABLED being False, makes the whole
layer a silent no-op — exactly like strategy_health/ai_narrator.py already
behaves when the API key isn't configured.
"""
