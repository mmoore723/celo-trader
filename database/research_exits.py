"""Durable, order-free authored exits; one compact row per research candidate."""
import json
import logging
import math
from datetime import timedelta

import pandas as pd

from database.connection import get_conn
from database.helpers import _now_et
from strategy_health.impulse_exit import et, executable_bid
from strategy_health.exit_protocols import SUPPORTED_PROTOCOL_PAIRS, first_exit
from database.research_exit_variants import pending_variants
from strategy_health.context_vwap_exit import PROTOCOLS as CONTEXT_VWAP_PROTOCOLS
from strategy_health.squeeze_exit import PROTOCOL as SQUEEZE_PROTOCOL

logger = logging.getLogger("celo_trader.research")
CREATE_TABLE = """CREATE TABLE IF NOT EXISTS research_strategy_exits (
    candidate_id TEXT PRIMARY KEY REFERENCES shadow_candidates(candidate_id),
    protocol TEXT NOT NULL, contract_symbol TEXT NOT NULL,
    entry_ask REAL NOT NULL, entry_quote_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'collecting', decision_at TEXT, reason TEXT,
    detected_at TEXT, bid REAL, bid_at TEXT, received_at TEXT
)"""
CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_research_exits_pending ON research_strategy_exits(status)"
EXIT_REASONS = {"underlying_stop", "underlying_2r_target", "underlying_1_5r_target", "underlying_2_06r_target", "underlying_vwap_target", "time_cap_120m",
                "session_flatten", "end_of_available_session", "opposite_flip", "atr_trailing_stop", "time_cap_75bars",
                "prior_high_target", "five_minute_close_below_vwap", "eod_1555_cap"}


def pending_exits(account, now):
    """Enroll only newly stamped candidates, never relabel historical tests."""
    with get_conn() as conn:
        for strategy_id, protocol in SUPPORTED_PROTOCOL_PAIRS:
            conn.execute("""INSERT OR IGNORE INTO research_strategy_exits
            (candidate_id,protocol,contract_symbol,entry_ask,entry_quote_at)
            SELECT s.candidate_id,?,q.contract_symbol,q.ask,q.observed_at
            FROM shadow_candidates s JOIN candidate_option_quote_observations q
            ON q.candidate_id=s.candidate_id AND q.observation_kind='entry'
            WHERE s.strategy_id=? AND COALESCE(s.broker_account_id,'')=?
            AND s.observed_at>=? AND q.source='tradier_research_contract_v1'
            AND q.ask>0 AND json_valid(s.metadata_json)
            AND json_extract(s.metadata_json,'$.authored_exit_protocol')=?""",
                (protocol, strategy_id, account or '', (et(now)-timedelta(days=2)).date().isoformat(), protocol))
        protocols = [protocol for _, protocol in SUPPORTED_PROTOCOL_PAIRS]
        placeholders = ','.join('?' for _ in protocols)
        originals = [dict(row, evidence_table="research_strategy_exits") for row in conn.execute(f"""SELECT e.*,s.ticker,s.trigger_bar,
            s.direction,s.metadata_json FROM research_strategy_exits e
            JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
            WHERE e.protocol IN ({placeholders}) AND e.status IN ('collecting','pending_quote')
            AND COALESCE(s.broker_account_id,'')=? ORDER BY s.trigger_bar""",
            (*protocols, account or ''))]
        return originals + pending_variants(conn, account, (et(now)-timedelta(days=2)).date().isoformat())


def capture_authored_exits(*, account, bars_lookup, quote_lookup, stopped=lambda: False, clock=_now_et, ema_bars_lookup=None):
    """Read-only broker callbacks; persist the first trigger before quote I/O."""
    if stopped():
        return
    frames, quotes = {}, {}
    def cached_quote(symbol):
        if symbol not in quotes:
            quotes[symbol] = (None, clock())
            quotes[symbol] = (quote_lookup(symbol), clock())
        return quotes[symbol]

    for row in pending_exits(account, clock()):
        if stopped():
            break
        try:
            table = row["evidence_table"]
            if table not in {"research_strategy_exits", "research_strategy_exit_variants"}:
                raise ValueError("Unknown evidence table")
            identity = (row["candidate_id"], row["protocol"])
            now = et(clock())
            from strategy_health.context_orb_exit import PREMIUM_PROTOCOLS
            if row['protocol'] in PREMIUM_PROTOCOLS.values() or row['protocol']==SQUEEZE_PROTOCOL:
                from database.research_premium_exits import capture
                ticker=row['ticker']
                if ticker not in frames:
                    frames[ticker]=bars_lookup(ticker)
                capture(row, frames[ticker] if frames[ticker] is not None else pd.DataFrame(), cached_quote, clock)
                continue
            if row["status"] == "collecting":
                meta = json.loads(row["metadata_json"])
                entry = et(row["trigger_bar"])
                if not math.isfinite(row["entry_ask"]):
                    event = (entry, "invalid_entry")
                elif entry.date() < now.date():
                    cap = entry.replace(hour=15,minute=55) if row['protocol'] in CONTEXT_VWAP_PROTOCOLS.values() else entry.replace(hour=16,minute=0)
                    event = (cap, "missed_session")
                else:
                    ticker = row["ticker"]
                    from strategy_health.ema_exit import PROTOCOL as EMA_PROTOCOL
                    from trading.research_ema_history import NATIVE_POLICY
                    use_native=(row['protocol']==EMA_PROTOCOL and meta.get('history_policy')==NATIVE_POLICY
                                and ema_bars_lookup is not None)
                    frame_key=(ticker,'native15') if use_native else ticker
                    if frame_key not in frames:
                        frames[frame_key] = None
                        frames[frame_key] = ema_bars_lookup(ticker) if use_native else bars_lookup(ticker)
                    frame = frames[frame_key]
                    event = first_exit(
                        row["protocol"], frame if frame is not None else pd.DataFrame(), entry_at=entry,
                        entry_quote_at=row["entry_quote_at"], meta=meta, direction=row["direction"], now=clock(),
                    )
                if event is None:
                    continue
                decision, reason = event
                status = "pending_quote" if reason in EXIT_REASONS else "unmeasurable"
                with get_conn() as conn:
                    conn.execute(f"""UPDATE {table} SET status=?,decision_at=?,
                        reason=?,detected_at=? WHERE candidate_id=? AND protocol=? AND status='collecting'""",
                        (status, decision.isoformat(), reason, et(clock()).isoformat(), *identity))
                    # A concurrent observer cannot replace the first latched decision.
                    row = dict(conn.execute(f"SELECT * FROM {table} WHERE candidate_id=? AND protocol=?",
                                            identity).fetchone())
                if row["status"] != "pending_quote":
                    continue
            decision, now = et(row["decision_at"]), et(clock())
            quote_deadline = decision + timedelta(minutes=1 if row['protocol'] in CONTEXT_VWAP_PROTOCOLS.values() else 5)
            if now > quote_deadline:
                with get_conn() as conn:
                    conn.execute(f"""UPDATE {table} SET status='missing_quote'
                        WHERE candidate_id=? AND protocol=? AND status='pending_quote'""", identity)
                continue
            symbol = row["contract_symbol"]
            quote, received = cached_quote(symbol)
            if et(received)>quote_deadline:
                continue
            priced = executable_bid(quote, contract=symbol, decision_at=decision, received_at=received)
            if priced is not None:
                with get_conn() as conn:
                    conn.execute(f"""UPDATE {table} SET status='priced',bid=?,bid_at=?,
                        received_at=? WHERE candidate_id=? AND protocol=? AND status='pending_quote'""",
                        (*priced, et(received).isoformat(), *identity))
        except Exception:
            logger.warning("Authored exit capture failed candidate=%s; continuing", row["candidate_id"], exc_info=True)
