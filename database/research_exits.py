"""Durable, order-free authored exits; one compact row per research candidate."""
import json
import logging
import math
from datetime import timedelta

import pandas as pd

from database.connection import get_conn
from database.helpers import _now_et
from strategy_health.impulse_exit import PROTOCOL, STRATEGY_ID, et, first_exit, executable_bid

logger = logging.getLogger("celo_trader.research")
CREATE_TABLE = """CREATE TABLE IF NOT EXISTS research_strategy_exits (
    candidate_id TEXT PRIMARY KEY REFERENCES shadow_candidates(candidate_id),
    protocol TEXT NOT NULL, contract_symbol TEXT NOT NULL,
    entry_ask REAL NOT NULL, entry_quote_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'collecting', decision_at TEXT, reason TEXT,
    detected_at TEXT, bid REAL, bid_at TEXT, received_at TEXT
)"""
CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_research_exits_pending ON research_strategy_exits(status)"
EXIT_REASONS = {"underlying_stop", "underlying_2r_target", "time_cap_120m",
                "session_flatten", "end_of_available_session"}


def pending_exits(account, now):
    """Enroll only newly stamped candidates, never relabel historical tests."""
    with get_conn() as conn:
        conn.execute("""INSERT OR IGNORE INTO research_strategy_exits
            (candidate_id,protocol,contract_symbol,entry_ask,entry_quote_at)
            SELECT s.candidate_id,?,q.contract_symbol,q.ask,q.observed_at
            FROM shadow_candidates s JOIN candidate_option_quote_observations q
            ON q.candidate_id=s.candidate_id AND q.observation_kind='entry'
            WHERE s.strategy_id=? AND COALESCE(s.broker_account_id,'')=?
            AND s.observed_at>=? AND q.source='tradier_research_contract_v1'
            AND q.ask>0 AND json_valid(s.metadata_json)
            AND json_extract(s.metadata_json,'$.authored_exit_protocol')=?""",
            (PROTOCOL, STRATEGY_ID, account or '', (et(now)-timedelta(days=2)).date().isoformat(), PROTOCOL))
        return [dict(row) for row in conn.execute("""SELECT e.*,s.ticker,s.trigger_bar,
            s.direction,s.metadata_json FROM research_strategy_exits e
            JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
            WHERE e.protocol=? AND e.status IN ('collecting','pending_quote')
            AND COALESCE(s.broker_account_id,'')=? ORDER BY s.trigger_bar""",
            (PROTOCOL, account or ''))]


def capture_authored_exits(*, account, bars_lookup, quote_lookup, stopped=lambda: False, clock=_now_et):
    """Read-only broker callbacks; persist the first trigger before quote I/O."""
    if stopped():
        return
    frames, quotes = {}, {}
    for row in pending_exits(account, clock()):
        if stopped():
            break
        try:
            now = et(clock())
            if row["status"] == "collecting":
                meta = json.loads(row["metadata_json"])
                entry = et(row["trigger_bar"])
                if not math.isfinite(row["entry_ask"]):
                    event = (entry, "invalid_entry")
                elif entry.date() < now.date():
                    event = (entry.replace(hour=16, minute=0), "missed_session")
                else:
                    ticker = row["ticker"]
                    if ticker not in frames:
                        frames[ticker] = None
                        frames[ticker] = bars_lookup(ticker)
                    frame = frames[ticker]
                    event = first_exit(
                        frame if frame is not None else pd.DataFrame(), entry_at=entry,
                        entry_quote_at=row["entry_quote_at"], stop=meta["underlying_stop"],
                        target=meta["underlying_target"], direction=row["direction"], now=clock(),
                    )
                if event is None:
                    continue
                decision, reason = event
                status = "pending_quote" if reason in EXIT_REASONS else "unmeasurable"
                with get_conn() as conn:
                    conn.execute("""UPDATE research_strategy_exits SET status=?,decision_at=?,
                        reason=?,detected_at=? WHERE candidate_id=? AND status='collecting'""",
                        (status, decision.isoformat(), reason, et(clock()).isoformat(), row["candidate_id"]))
                    # A concurrent observer cannot replace the first latched decision.
                    row = dict(conn.execute("SELECT * FROM research_strategy_exits WHERE candidate_id=?",
                                            (row["candidate_id"],)).fetchone())
                if row["status"] != "pending_quote":
                    continue
            decision, now = et(row["decision_at"]), et(clock())
            if now > decision + timedelta(minutes=5):
                with get_conn() as conn:
                    conn.execute("""UPDATE research_strategy_exits SET status='missing_quote'
                        WHERE candidate_id=? AND status='pending_quote'""", (row["candidate_id"],))
                continue
            symbol = row["contract_symbol"]
            if symbol not in quotes:
                quotes[symbol] = (None, clock())
                quotes[symbol] = (quote_lookup(symbol), clock())
            quote, received = quotes[symbol]
            priced = executable_bid(quote, contract=symbol, decision_at=decision, received_at=received)
            if priced is not None:
                with get_conn() as conn:
                    conn.execute("""UPDATE research_strategy_exits SET status='priced',bid=?,bid_at=?,
                        received_at=? WHERE candidate_id=? AND status='pending_quote'""",
                        (*priced, et(received).isoformat(), row["candidate_id"]))
        except Exception:
            logger.warning("Authored exit capture failed candidate=%s; continuing", row["candidate_id"], exc_info=True)
