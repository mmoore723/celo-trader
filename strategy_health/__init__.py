"""
strategy_health — built-in, permanent replacement for the one-off
diag_*.py / ab_test_*.py scripts.

Instead of me writing a new throwaway script every time we want to know
"did the signal survive to a real trade, and was it any good", this package
runs that same question automatically every trading day and stores the
answer in the database, where the dashboard can show it.

Modules:
  engine.py       — replays real strategy_router code against real market
                    data for one ticker/day, measuring raw signals vs what
                    survived the router's gates.
  narrator.py     — rule-based (free, no API) plain-English summary.
  ai_narrator.py  — optional Claude API summary (only runs if
                    config.ANTHROPIC_API_KEY is set; skips silently otherwise).
  runner.py       — orchestrates engine + both narrators + saves to DB.
                    Called automatically once/day from trading/loop.py, and
                    on-demand from api/routes/strategy_health.py.
"""
