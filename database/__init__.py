"""
database/ — SQLite persistence layer for the trading bot.

Split from the old single database.py into themed modules (2026-08-01,
file-size cleanup) — no logic changed anywhere, only relocated. This
__init__.py re-exports the exact same public names the old flat module did,
so every existing `from database import X` / `import database; database.X`
call site elsewhere in the app is unaffected:

  helpers.py        — _now_et, _to_et_isoformat, _merge_annotations_json
  schema.py          — table DDL, _init_db_at, init_db, backfill_daily_summaries
  connection.py       — get_conn, _conn_for_mode
  trades.py            — insert_trade, save_mtf_bias, close_trade
  trades_query.py       — get_open_trades, get_open_trade, get_all_trades
  summary.py             — _upsert_daily_summary, get_daily_summaries, get_cumulative_pnl
  events.py               — log_event, log_ai_reasoning, get_ai_reasoning_log/_entry
  stats.py                 — get_statistics
  strategy_audit.py         — save/get_latest/get_strategy_audit_history

Why SQLite instead of CSV?
  - Atomic writes prevent data corruption on unexpected shutdown.
  - Full SQL query support for complex reporting (P&L by day, win rate, drawdown).
  - Zero extra infrastructure; the file lives next to the bot.

Schema
------
trades        : every closed position (one row = one round-trip)
daily_summary : cached daily P&L rolled up each evening (speeds up the calendar heatmap)
system_events : API errors, alerts, kill-switch triggers for audit trail
"""

from database.helpers import _now_et, _to_et_isoformat, _merge_annotations_json
from database.schema import init_db, backfill_daily_summaries, _init_db_at
from database.connection import get_conn, _conn_for_mode
from database.trades import insert_trade, save_mtf_bias, close_trade, audit_trade_lineage
from database.option_quotes import (
    record_paper_option_quote, record_candidate_option_quote,
    capture_due_candidate_option_quotes,
)
from database.research_observations import (
    start_paper_research_observation, close_due_paper_research_observations,
    get_paper_research_scorecard,
)
from database.trades_query import get_open_trades, get_open_trade, get_all_trades
from database.summary import _upsert_daily_summary, get_daily_summaries, get_cumulative_pnl
from database.events import log_event, log_ai_reasoning, get_ai_reasoning_log, get_ai_reasoning_entry
from database.stats import get_statistics
from database.strategy_audit import (
    save_strategy_audit, get_latest_strategy_audit, get_strategy_audit_history,
)
from database.settings_audit import record_strategy_setting_changes, get_strategy_setting_changes
from database.broker_order_flow import (
    record_broker_order_event, link_broker_order_to_trade, get_broker_order_flow,
)

__all__ = [
    "_now_et", "_to_et_isoformat", "_merge_annotations_json",
    "init_db", "backfill_daily_summaries", "_init_db_at",
    "get_conn", "_conn_for_mode",
    "insert_trade", "save_mtf_bias", "close_trade", "audit_trade_lineage", "record_paper_option_quote",
    "record_candidate_option_quote", "capture_due_candidate_option_quotes",
    "start_paper_research_observation", "close_due_paper_research_observations", "get_paper_research_scorecard",
    "get_open_trades", "get_open_trade", "get_all_trades",
    "_upsert_daily_summary", "get_daily_summaries", "get_cumulative_pnl",
    "log_event", "log_ai_reasoning", "get_ai_reasoning_log", "get_ai_reasoning_entry",
    "get_statistics",
    "save_strategy_audit", "get_latest_strategy_audit", "get_strategy_audit_history",
    "record_strategy_setting_changes", "get_strategy_setting_changes",
    "record_broker_order_event", "link_broker_order_to_trade", "get_broker_order_flow",
]
