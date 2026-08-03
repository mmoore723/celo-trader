"""
database/schema.py — Table DDL, per-file schema init/migration
(_init_db_at), the public init_db() bootstrap (including the one-time
root -> user_data/ data migration), and daily_summary backfill.

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.

Kept together as one file rather than split further: the DDL constants,
_init_db_at, init_db, and backfill_daily_summaries are one cohesive
schema-bootstrapping unit — _init_db_at directly executes the DDL constants
above it, init_db calls _init_db_at for both DB files then calls
backfill_daily_summaries, and splitting them apart would separate each
function from the constants/helpers it's built directly on top of.
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path

from config import get_db_path

logger = logging.getLogger("celo_trader.database")

# ── Schema DDL ────────────────────────────────────────────────────────────────

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    contract_symbol TEXT    NOT NULL,   -- OCC option symbol e.g. AMC230120C00005000
    option_type     TEXT    NOT NULL,   -- 'call' or 'put'
    strike          REAL    NOT NULL,
    expiry          TEXT    NOT NULL,   -- ISO date string YYYY-MM-DD
    contracts       INTEGER NOT NULL,   -- number of contracts (each = 100 shares)
    entry_price     REAL    NOT NULL,   -- per-contract price paid
    exit_price      REAL,               -- per-contract price received (NULL while open)
    entry_time      TEXT    NOT NULL,   -- ISO datetime
    exit_time       TEXT,               -- ISO datetime (NULL while open)
    entry_reason    TEXT,               -- which signal triggered entry
    exit_reason     TEXT,               -- 'stop_loss' | 'take_profit' | 'manual' | 'eod'
    realized_pnl    REAL,               -- (exit_price - entry_price) * contracts * 100
    status          TEXT    NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
    paper           INTEGER NOT NULL DEFAULT 1,        -- 1=paper, 0=live
    strategy_id     TEXT    DEFAULT 'INST_ORB',        -- which router strategy generated signal
    tier            TEXT    NOT NULL DEFAULT 'main',   -- 'main' | 'opportunity'
    broker_account_id TEXT                             -- account/mode identity at entry
);
"""

_CREATE_TRADES_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_trades_broker_account ON trades(broker_account_id, entry_time);",
]

_CREATE_DAILY_SUMMARY = """
CREATE TABLE IF NOT EXISTS daily_summary (
    trade_date  TEXT PRIMARY KEY,   -- YYYY-MM-DD
    total_pnl   REAL NOT NULL DEFAULT 0,
    num_trades  INTEGER NOT NULL DEFAULT 0,
    num_wins    INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_SYSTEM_EVENTS = """
CREATE TABLE IF NOT EXISTS system_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,   -- ISO datetime
    level       TEXT    NOT NULL,   -- 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
    component   TEXT    NOT NULL,   -- e.g. 'broker', 'signals', 'risk'
    message     TEXT    NOT NULL
);
"""

_CREATE_STRATEGY_AUDITS = """
CREATE TABLE IF NOT EXISTS strategy_audits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_date    TEXT    NOT NULL,   -- YYYY-MM-DD (daily) or ISO year-week e.g. "2026-W29" (weekly)
    audit_type    TEXT    NOT NULL DEFAULT 'daily',  -- 'daily' | 'weekly' — added 2026-07-20
    created_at    TEXT    NOT NULL,   -- ISO datetime the audit ran
    tickers       TEXT,               -- comma-separated tickers scanned
    aggregate_json TEXT   NOT NULL,   -- full per-strategy funnel dict, JSON-encoded
    rule_summary  TEXT,               -- free, rule-based plain-English summary
    ai_summary    TEXT                -- optional Claude-generated summary (NULL if no API key)
);
"""

# ai_reasoning_log — every prompt/response the AI reasoning layer sends or
# receives, win or lose. Written by ai_reasoning/narrator.py (phase 1,
# event_type='entry_narration'/'exit_narration') and, once approved,
# ai_reasoning/decision_support.py (phase 2, event_type='entry_veto'). This
# is the full replay trail the user asked for before any decision-support
# power over live trades is considered — every call is logged here
# regardless of success, timeout, or error, never only the successful ones.
_CREATE_AI_REASONING_LOG = """
CREATE TABLE IF NOT EXISTS ai_reasoning_log (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                     TEXT    NOT NULL,   -- ISO datetime (ET) the call was made
    event_type             TEXT    NOT NULL,   -- 'entry_narration' | 'exit_narration' | 'entry_veto'
    ticker                 TEXT    NOT NULL,
    trade_id               INTEGER,            -- FK to trades.id where applicable (NULL if not yet inserted)
    feature_snapshot_json  TEXT    NOT NULL,   -- exact input dict sent to the model, JSON-encoded
    prompt                 TEXT    NOT NULL,   -- full system+user prompt text, for replay
    response_text          TEXT,               -- raw model output (NULL on failure/timeout)
    latency_ms             INTEGER,
    model                  TEXT,
    error                  TEXT,               -- non-NULL if the call failed, timed out, or was skipped
    applied                INTEGER NOT NULL DEFAULT 0   -- phase 2 only: was a veto/resize actually acted on
);
"""

# signal_journal — one row per strategy signal's FINAL outcome, win or lose.
# Added 2026-07-24 per explicit user request: neither bot.log (unstructured
# text dump) nor ai_reasoning_log (narrates realized entries/exits only) can
# answer "why didn't the bot trade today" — this table is the queryable
# answer. Written by signal_journal.py::log_signal_outcome(), called from
# router_gates.py (pre-entry.py gates: confidence floor, grade filter,
# conflict veto, volume ROC veto, directional consensus, regime gate) and
# trading/entry.py (budget, spread, R:R, sizing, macro VWAP gates, and the
# final 'entered' outcome on a successful trade).
_CREATE_SIGNAL_JOURNAL = """
CREATE TABLE IF NOT EXISTS signal_journal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,   -- ISO datetime (ET)
    ticker        TEXT    NOT NULL,
    strategy_id   TEXT    NOT NULL,
    direction     TEXT    NOT NULL,   -- 'bullish' | 'bearish'
    confidence    REAL    NOT NULL,   -- 0.0-1.0 at the moment of this outcome
    outcome       TEXT    NOT NULL,   -- 'entered' | 'blocked'
    reason_code   TEXT,               -- NULL when outcome='entered' — see signal_journal.REASON_CODES
    reason_detail TEXT,               -- human-readable specifics, e.g. "needs $88, cap is $69"
    trade_id      INTEGER,            -- linked real trade for outcome='entered'
    context_json  TEXT,               -- strategy metadata / selected-contract context at decision time
    tier          TEXT    NOT NULL DEFAULT 'main' -- 'main' | 'opportunity'
);
"""
_CREATE_SIGNAL_JOURNAL_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_signal_journal_ts ON signal_journal(ts);",
    "CREATE INDEX IF NOT EXISTS idx_signal_journal_ticker ON signal_journal(ticker);",
    "CREATE INDEX IF NOT EXISTS idx_signal_journal_trade_id ON signal_journal(trade_id);",
]

# option_quote_observations — durable, executable quote evidence for paper
# trades.  This is deliberately separate from `trades`: a position can have
# many marks, while a trade must remain one compact round-trip row.  Quotes are
# recorded at entry, once per minute while a paper position is open, and at a
# confirmed exit.  They are research telemetry only; this table must never be
# consulted by order-placement code.
_CREATE_OPTION_QUOTE_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS option_quote_observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id         INTEGER NOT NULL,
    observed_at      TEXT    NOT NULL,
    observed_minute  TEXT    NOT NULL,
    observation_kind TEXT    NOT NULL, -- entry | mark | exit
    contract_symbol  TEXT    NOT NULL,
    bid              REAL,
    ask              REAL,
    mid              REAL,
    last             REAL,
    fill_price       REAL,
    source           TEXT    NOT NULL,
    FOREIGN KEY(trade_id) REFERENCES trades(id)
);
"""
_CREATE_OPTION_QUOTE_OBSERVATIONS_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_option_quote_trade_time ON option_quote_observations(trade_id, observed_at);",
    # Per-minute marks prevent a fast polling loop from turning one paper trade
    # into thousands of database writes. Entry and exit retain their own rows.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_option_quote_unique_minute ON option_quote_observations(trade_id, observation_kind, observed_minute);",
]

# shadow_candidates — paper-only evidence for every strategy signal that the
# live router actually evaluated, including those later rejected by a gate.
# This is an audit ledger, never an order queue: no execution code may read it
# to place, size, or close a trade.
_CREATE_SHADOW_CANDIDATES = """
CREATE TABLE IF NOT EXISTS shadow_candidates (
    candidate_id       TEXT PRIMARY KEY,
    observed_at        TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    strategy_id        TEXT NOT NULL,
    direction          TEXT NOT NULL,
    confidence         REAL NOT NULL,
    trigger_bar        TEXT,
    tier               TEXT NOT NULL DEFAULT 'main',
    broker_account_id  TEXT,
    metadata_json      TEXT,
    final_outcome      TEXT NOT NULL DEFAULT 'pending',
    gate_reason        TEXT,
    gate_detail        TEXT,
    linked_trade_id    INTEGER,
    resolved_at        TEXT
);
"""
_CREATE_SHADOW_CANDIDATES_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_shadow_candidates_observed ON shadow_candidates(observed_at);",
    "CREATE INDEX IF NOT EXISTS idx_shadow_candidates_strategy ON shadow_candidates(strategy_id, final_outcome);",
]



# ── Initialisation ────────────────────────────────────────────────────────────

def _init_db_at(db_path: Path) -> None:
    """
    Internal helper: create all tables and run migrations on ONE specific
    SQLite file (paper or live). Operates on `db_path` directly — does NOT
    call get_db_path() / get_conn(), so it's safe to call for either DB
    regardless of which mode is currently active in user_settings.json.
    """
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        conn.execute(_CREATE_TRADES)
        conn.execute(_CREATE_DAILY_SUMMARY)
        conn.execute(_CREATE_SYSTEM_EVENTS)
        conn.execute(_CREATE_STRATEGY_AUDITS)
        conn.execute(_CREATE_AI_REASONING_LOG)
        conn.execute(_CREATE_SIGNAL_JOURNAL)
        conn.execute(_CREATE_OPTION_QUOTE_OBSERVATIONS)
        conn.execute(_CREATE_SHADOW_CANDIDATES)
        for _idx_sql in _CREATE_TRADES_IDX:
            conn.execute(_idx_sql)
        for _idx_sql in _CREATE_SIGNAL_JOURNAL_IDX:
            conn.execute(_idx_sql)
        for _idx_sql in _CREATE_OPTION_QUOTE_OBSERVATIONS_IDX:
            conn.execute(_idx_sql)
        for _idx_sql in _CREATE_SHADOW_CANDIDATES_IDX:
            conn.execute(_idx_sql)
        # ── Migrations ────────────────────────────────────────────────────────
        _cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
        if "strategy_id" not in _cols:
            conn.execute(
                "ALTER TABLE trades ADD COLUMN strategy_id TEXT DEFAULT 'INST_ORB'"
            )
            logger.info("Migration: added strategy_id column to %s", db_path.name)
        if "stop_price" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN stop_price REAL")
            logger.info("Migration: added stop_price column to %s", db_path.name)
        if "target_price" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN target_price REAL")
            logger.info("Migration: added target_price column to %s", db_path.name)
        if "peak_price" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN peak_price REAL")
            logger.info("Migration: added peak_price (MFE) column to %s", db_path.name)
        if "mae_price" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN mae_price REAL")
            logger.info("Migration: added mae_price (MAE) column to %s", db_path.name)
        if "recap" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN recap TEXT")
            logger.info("Migration: added recap column to %s", db_path.name)
        if "annotations_json" not in _cols:
            # JSON-encoded list of the bot's own chart annotations (FVG zones,
            # BOS/TREND_CONT levels, entry/exit markers) captured at entry and
            # exit time — see trading/annotations.py::snapshot_annotations().
            # Lets Journal replay show WHY a trade fired, not just that it did,
            # for trades from any past day (the live annotation buffer this is
            # copied from is ephemeral and gets overwritten).
            conn.execute("ALTER TABLE trades ADD COLUMN annotations_json TEXT")
            logger.info("Migration: added annotations_json column to %s", db_path.name)
        _audit_cols = {row[1] for row in conn.execute("PRAGMA table_info(strategy_audits)")}
        if "audit_type" not in _audit_cols:
            # Existing rows are all from the daily audit (weekly didn't exist
            # yet), so backfill them explicitly rather than leaving NULL.
            conn.execute("ALTER TABLE strategy_audits ADD COLUMN audit_type TEXT DEFAULT 'daily'")
            conn.execute("UPDATE strategy_audits SET audit_type = 'daily' WHERE audit_type IS NULL")
            logger.info("Migration: added audit_type column to strategy_audits in %s", db_path.name)
        if "mtf_bias_json" not in _cols:
            # JSON dict of {"1Min": "with"|"against"|"neutral", "5Min": ..., ...} —
            # higher-timeframe trend agreement at entry, for Journal's MTF
            # alignment heat map. Teaching overlay only — see
            # trading/mtf_features.py::compute_mtf_alignment(). Saved as a
            # best-effort follow-up AFTER insert_trade() succeeds, so this
            # column can be NULL even on a fully valid trade if that lookup
            # failed or was skipped — treat NULL as "unknown", not an error.
            conn.execute("ALTER TABLE trades ADD COLUMN mtf_bias_json TEXT")
            logger.info("Migration: added mtf_bias_json column to %s", db_path.name)
        if "tier" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN tier TEXT NOT NULL DEFAULT 'main'")
            logger.info("Migration: added tier column to trades in %s", db_path.name)
        if "broker_account_id" not in _cols:
            conn.execute("ALTER TABLE trades ADD COLUMN broker_account_id TEXT")
            logger.info("Migration: added broker_account_id to trades in %s", db_path.name)
        _shadow_cols = {row[1] for row in conn.execute("PRAGMA table_info(shadow_candidates)")}
        if "broker_account_id" not in _shadow_cols:
            conn.execute("ALTER TABLE shadow_candidates ADD COLUMN broker_account_id TEXT")
            logger.info("Migration: added broker_account_id to shadow_candidates in %s", db_path.name)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_candidates_account "
            "ON shadow_candidates(broker_account_id, observed_at)"
        )
        _journal_cols = {row[1] for row in conn.execute("PRAGMA table_info(signal_journal)")}
        if "trade_id" not in _journal_cols:
            conn.execute("ALTER TABLE signal_journal ADD COLUMN trade_id INTEGER")
            logger.info("Migration: added trade_id to signal_journal in %s", db_path.name)
        if "context_json" not in _journal_cols:
            conn.execute("ALTER TABLE signal_journal ADD COLUMN context_json TEXT")
            logger.info("Migration: added context_json to signal_journal in %s", db_path.name)
        if "tier" not in _journal_cols:
            conn.execute("ALTER TABLE signal_journal ADD COLUMN tier TEXT NOT NULL DEFAULT 'main'")
            logger.info("Migration: added tier column to signal_journal in %s", db_path.name)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("Database initialised at %s", db_path)


def init_db() -> None:
    """
    Create tables if they don't already exist.  Safe to call on every startup.

    Initialises BOTH trades_paper.db AND trades_live.db at startup so the live
    DB always has all migration columns ready — even when the user has never
    traded live before.  This prevents "no such column: peak_price" errors on
    the first live-mode close_trade() call.

    One-time migration: if the active DB directory is NOT the project root
    (i.e. we are using the new per-user layout under user_data/admin/) and the
    old root-level DB files still exist, copy them to the new location BEFORE
    creating/migrating the schema.  This ensures historical trades remain visible
    after the config change.  The copy is skipped on all subsequent startups
    because the destination already exists.
    """
    import shutil as _shutil
    _db_dir  = get_db_path().parent
    _paper_p = _db_dir / "trades_paper.db"
    _live_p  = _db_dir / "trades_live.db"

    # ── One-time data migration from root → user_data/admin/ ──────────────────
    # get_db_path() used to return root/trades_paper.db; it now returns
    # user_data/admin/trades_paper.db.  Copy old root-level DBs to the new
    # path if (a) they don't exist at the new path yet, OR (b) they exist but
    # are empty (created by a prior startup before this migration ran).
    # We copy BEFORE _init_db_at() so schema creation doesn't interfere.
    _root = Path(__file__).resolve().parent
    for _fname, _dst in [("trades_paper.db", _paper_p), ("trades_live.db", _live_p)]:
        _src = _root / _fname
        if not _src.exists() or _src.resolve() == _dst.resolve():
            continue  # nothing to migrate
        _needs_copy = not _dst.exists()
        if not _needs_copy and _dst.exists():
            # Destination exists — only overwrite if it has NO trades yet
            try:
                _chk = sqlite3.connect(str(_dst))
                _row = _chk.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='trades'"
                ).fetchone()
                _has_table = _row and _row[0] > 0
                if _has_table:
                    _cnt = _chk.execute("SELECT COUNT(*) FROM trades").fetchone()
                    _needs_copy = (_cnt is None or _cnt[0] == 0)
                else:
                    _needs_copy = True   # no trades table → effectively empty
                _chk.close()
            except Exception:
                _needs_copy = True   # can't read → treat as empty, overwrite
        if _needs_copy:
            try:
                _dst.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copy2(_src, _dst)
                logger.info("init_db: migrated %s → %s", _src, _dst)
            except Exception as _copy_err:
                logger.warning("init_db: could not migrate %s: %s", _fname, _copy_err)

    for _db in (_paper_p, _live_p):
        try:
            _init_db_at(_db)
        except Exception as _e:
            logger.warning("init_db: failed to init %s: %s", _db.name, _e)

    # Rebuild daily_summary from any closed trades that slipped through
    # (e.g. trades closed before this function existed, or after a transient error).
    backfill_daily_summaries()


def backfill_daily_summaries() -> None:
    """
    Rebuild daily_summary from all closed trades that have no corresponding row.

    Safe to call on every startup — uses INSERT OR REPLACE so existing accurate
    rows are refreshed and missing rows are created.  Handles the common case
    where daily_summary was empty despite closed trades existing in the trades
    table (e.g. bot crash between close_trade() and _upsert_daily_summary(), or
    trades created by earlier code that predates the summary feature).
    """
    from collections import defaultdict
    # Lazy import: connection.py imports _init_db_at from this module, so a
    # top-level import here would be circular. get_conn is only needed at
    # call time, not at module-load time, so a local import breaks the cycle.
    from database.connection import get_conn
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT exit_time, realized_pnl FROM trades "
                "WHERE status = 'closed' AND exit_time IS NOT NULL AND realized_pnl IS NOT NULL"
            ).fetchall()

        if not rows:
            return

        # Aggregate P&L / trade count / wins by calendar date
        daily: dict = defaultdict(lambda: {"total_pnl": 0.0, "num_trades": 0, "num_wins": 0})
        for r in rows:
            try:
                d = str(r["exit_time"])[:10]   # YYYY-MM-DD prefix of ISO string
                pnl = float(r["realized_pnl"])
                daily[d]["total_pnl"]   += pnl
                daily[d]["num_trades"]  += 1
                if pnl > 0:
                    daily[d]["num_wins"] += 1
            except Exception:
                pass

        # Write — INSERT OR REPLACE overwrites stale rows and inserts missing ones
        with get_conn() as conn:
            for d, vals in daily.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO daily_summary (trade_date, total_pnl, num_trades, num_wins)
                    VALUES (?, ?, ?, ?)
                    """,
                    (d, round(vals["total_pnl"], 4), vals["num_trades"], vals["num_wins"]),
                )

        logger.info("backfill_daily_summaries: synced %d date(s)", len(daily))
    except Exception as e:
        logger.warning("backfill_daily_summaries failed (non-fatal): %s", e)
