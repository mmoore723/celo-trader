"""
signal_journal/ — Structured "why did/didn't the bot trade" log.

Built 2026-07-24 per explicit user request: bot.log is a 50MB/day unstructured
dump, and the existing ai_reasoning_log (database.py) only narrates REALIZED
entries/exits — it's silent on blocked signals, which is exactly what the user
needed to see (e.g. the BABA 2026-07-24 near-miss: 77%-confidence signal,
cleared every other gate, blocked at the final budget check — invisible in
both bot.log's raw text and ai_reasoning_log's entry/exit-only scope).

This module is the single write path for "what happened to this signal":
  outcome='entered' — the signal became a real trade
  outcome='blocked' — a gate stopped it, with a short reason_code (for
                       aggregation/filtering) and a human-readable reason_detail

Every call is a DUAL WRITE, same pattern as database.py::log_event():
  1. INSERT into the signal_journal table — the persisted, queryable record.
  2. Mirror to bot.log via the structured JSON logger with the same fields in
     extra={}, so the existing live-tail WebSocket (api/routes/ws.py) picks it
     up in real time with badge-ready fields — the Thinking panel updates live
     exactly as it does today, it just now carries structured data too.

Never raises into the trading loop — a journal write failure must never be
allowed to affect a real trade decision (same non-fatal contract as
database.py::log_ai_reasoning()).

Split further out of the old single signal_journal.py (2026-08-01,
file-size cleanup) into:
  - constants.py: REASON_CODES
  - write.py:     log_signal_outcome() — the single write path
  - queries.py:   get_todays_rows(), get_todays_summary(),
                   get_latest_per_ticker_today(), get_trend()

No monkeypatching of this module's names was found anywhere in the
codebase (grep-verified), so this __init__.py just re-exports normally.
"""
from __future__ import annotations

from signal_journal.constants import REASON_CODES
from signal_journal.write import log_signal_outcome
from signal_journal.queries import (
    get_todays_rows,
    get_todays_summary,
    get_latest_per_ticker_today,
    get_trend,
)

__all__ = [
    "REASON_CODES",
    "log_signal_outcome",
    "get_todays_rows",
    "get_todays_summary",
    "get_latest_per_ticker_today",
    "get_trend",
]
