"""
database.py — SQLite persistence layer for the trading bot.

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

import sqlite3
import logging
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pytz

from config import get_db_path   # dynamic resolver: paper → trades_paper.db, live → trades_live.db

logger = logging.getLogger("celo_trader.database")

# ── Timezone helper ───────────────────────────────────────────────────────────
_ET = pytz.timezone("US/Eastern")


def _now_et() -> datetime:
    """
    Return the current wall-clock time in US/Eastern as a tz-aware datetime.
    All timestamps stored in this module use this function so the database
    always records ET times regardless of server locale or UTC offset changes
    (e.g. DST transitions).
    """
    return datetime.now(_ET)


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
    strategy_id     TEXT    DEFAULT 'INST_ORB'         -- which router strategy generated signal
);
"""

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


# ── Connection context manager ────────────────────────────────────────────────

@contextmanager
def get_conn():
    """
    Yield a SQLite connection for the *currently active* trading database.

    The active file is resolved fresh on every call via get_db_path() so that
    toggling paper_trading in the UI takes effect immediately without restart:
      paper_trading = True  → trades_paper.db
      paper_trading = False → trades_live.db

    WAL mode is enabled for safe concurrent readers (dashboard + bot loop).
    Commits on clean exit, rolls back on any exception.
    """
    _active_path = get_db_path()
    conn = sqlite3.connect(str(_active_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Initialisation ────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create tables if they don't already exist.  Safe to call on every startup.

    Initialises whichever database file is currently active (paper or live) so
    both files get the full schema the first time each mode is used.
    """
    _active_path = get_db_path()
    with get_conn() as conn:
        conn.execute(_CREATE_TRADES)
        conn.execute(_CREATE_DAILY_SUMMARY)
        conn.execute(_CREATE_SYSTEM_EVENTS)
        # ── Migrations ────────────────────────────────────────────────────────
        # Add strategy_id column if upgrading from a pre-router schema.
        # ALTER TABLE IF NOT EXISTS is not supported in older SQLite; use
        # the column-list inspection approach instead.
        _cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
        if "strategy_id" not in _cols:
            conn.execute(
                "ALTER TABLE trades ADD COLUMN strategy_id TEXT DEFAULT 'INST_ORB'"
            )
            logger.info("Migration: added strategy_id column to trades table")
    logger.info("Database initialised at %s", _active_path)
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


# ── Trade CRUD ────────────────────────────────────────────────────────────────

def _to_et_isoformat(dt: datetime) -> str:
    """
    Normalise any datetime to a tz-naive US/Eastern ISO string.

    Two cases:
      • tz-naive  → assumed to already be in ET (all bar timestamps, sim times,
                    and _now_et().replace(tzinfo=None) are ET-naive). Localize
                    directly to ET so DST is acknowledged, then strip tzinfo so
                    the stored string is tz-naive ET.
      • tz-aware  → convert to ET, then strip tzinfo.

    Why tz-naive output?
      The Plotly chart's x-axis is built from df["time"] which is tz-naive ET
      (produced by bars_to_df()). Storing tz-aware strings would cause Plotly to
      UTC-shift marker positions away from their candle — the most common symptom
      is markers appearing 4 hours to the left of the bar they belong to.
    """
    if dt.tzinfo is None:
        # Localize as ET (acknowledges DST). The naive value is already wall-clock ET.
        dt = _ET.localize(dt)
    else:
        dt = dt.astimezone(_ET)
    # Return without tzinfo so the string matches tz-naive chart timestamps
    return dt.replace(tzinfo=None).isoformat()


def insert_trade(
    ticker: str,
    contract_symbol: str,
    option_type: str,
    strike: float,
    expiry: str,
    contracts: int,
    entry_price: float,
    entry_time: datetime,
    entry_reason: str,
    paper: bool = True,
    strategy_id: str = "INST_ORB",   # which router strategy generated this signal
) -> int:
    """
    Insert an open trade.  Returns the new row id so we can update it on close.
    All timestamps stored as US/Eastern ISO strings for session-time alignment.
    """
    sql = """
        INSERT INTO trades
            (ticker, contract_symbol, option_type, strike, expiry,
             contracts, entry_price, entry_time, entry_reason, status, paper, strategy_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (
            ticker, contract_symbol, option_type, strike, expiry,
            contracts, entry_price, _to_et_isoformat(entry_time), entry_reason,
            1 if paper else 0, strategy_id,
        ))
        trade_id = cur.lastrowid
    logger.info(
        "Trade %d opened: %s %s @ %.2f [strategy=%s]",
        trade_id, ticker, contract_symbol, entry_price, strategy_id,
    )
    return trade_id


def close_trade(
    trade_id: int,
    exit_price: float,
    exit_time: datetime,
    exit_reason: str,
    confirmed_fill_price: Optional[float] = None,
) -> float:
    """
    Mark a trade closed and compute realised P&L.
    FIX N2: If confirmed_fill_price is provided (from broker fill confirmation),
    use that for P&L calculation instead of intended exit_price.
    Returns the realised P&L in dollars.
    """
    actual_exit = confirmed_fill_price if confirmed_fill_price else exit_price

    with get_conn() as conn:
        row = conn.execute(
            "SELECT entry_price, contracts FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Trade id {trade_id} not found in database")

        entry_price  = row["entry_price"]
        contracts    = row["contracts"]
        realized_pnl = (actual_exit - entry_price) * contracts * 100

        conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, exit_time = ?, exit_reason = ?,
                realized_pnl = ?, status = 'closed'
            WHERE id = ?
            """,
            (actual_exit, _to_et_isoformat(exit_time), exit_reason, realized_pnl, trade_id),
        )

    logger.info(
        "Trade %d closed: exit=%.4f (confirmed=%.4f) reason=%s pnl=$%.2f",
        trade_id, exit_price, actual_exit, exit_reason, realized_pnl,
    )

    # Update daily summary — wrapped so a transient DB error never blocks the close
    try:
        _upsert_daily_summary(exit_time.date(), realized_pnl)
    except Exception as _e:
        logger.warning("_upsert_daily_summary failed (non-fatal): %s — will backfill on next startup", _e)

    # Reflect P&L in last_known_balance so the dashboard shows the correct balance
    # even when the bot is in STANDBY (not actively fetching Alpaca account equity).
    # The broker-fetch path in trading_logic._tick() will override this with the
    # authoritative Alpaca value the next time the bot runs.
    try:
        from config import get_settings as _gs, save_settings as _ss
        _cur_bal = float(_gs().get("last_known_balance") or 0.0)
        _ss({"last_known_balance": round(_cur_bal + realized_pnl, 2)})
    except Exception as _e:
        logger.warning("Could not update last_known_balance after trade close: %s", _e)

    return realized_pnl


def get_open_trades() -> list[dict]:
    """
    Return ALL currently-open trades (newest first), supporting up to
    MAX_CONCURRENT_POSITIONS simultaneous positions.

    If more than MAX_CONCURRENT_POSITIONS BOT-MANAGED trades are open (should
    never happen — the entry gate in trading_logic._tick() checks this count
    before placing a new order), log a CRITICAL alert since that indicates a
    bug or a manually-placed order, but still return every row so the caller
    can manage (and exit) all of them.

    FIX 2026-06-15: rows with strategy_id == "RECOVERED_UNTRACKED" (the 7
    legacy positions recovered from the ghost-position reconciliation) are
    EXCLUDED from this count. They're real open positions and are still
    returned in the list (so the Trade Journal's "Close Position" buttons and
    trading_logic._tick()'s own RECOVERED_UNTRACKED filter can see them), but
    they were never opened by this bot's MAX_CONCURRENT_POSITIONS-gated entry
    logic, so they shouldn't trip a "DATA INTEGRITY" alert or be counted
    against the 2-position cap.
    """
    from config import MAX_CONCURRENT_POSITIONS
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
        ).fetchall()
    _bot_managed = [r for r in rows if r["strategy_id"] != "RECOVERED_UNTRACKED"]
    if len(_bot_managed) > MAX_CONCURRENT_POSITIONS:
        logger.error(
            "DATA INTEGRITY: %d open trades found (expected max %d). Trade IDs: %s.",
            len(_bot_managed), MAX_CONCURRENT_POSITIONS, [r["id"] for r in _bot_managed],
        )
        log_event("CRITICAL", "database",
                  f"More open trades ({len(_bot_managed)}) than the {MAX_CONCURRENT_POSITIONS}-position "
                  f"limit allows: {[r['id'] for r in _bot_managed]}")
    return [dict(r) for r in rows]


def get_open_trade() -> Optional[dict]:
    """
    Backward-compat helper — returns the single MOST RECENT open trade, or
    None. Used by manual-close / panic-close paths that only ever act on
    one position at a time. Multi-position management should use
    get_open_trades() instead.
    """
    trades = get_open_trades()
    return trades[0] if trades else None


def get_all_trades(limit: int = 500) -> list[dict]:
    """Return closed trades newest-first, for the trade journal page."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Daily summary ─────────────────────────────────────────────────────────────

def _upsert_daily_summary(trade_date: date, pnl: float) -> None:
    """Increment (or insert) the daily summary row when a trade closes."""
    ds = trade_date.isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT total_pnl, num_trades, num_wins FROM daily_summary WHERE trade_date = ?",
            (ds,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE daily_summary
                SET total_pnl  = total_pnl  + ?,
                    num_trades = num_trades + 1,
                    num_wins   = num_wins   + ?
                WHERE trade_date = ?
                """,
                (pnl, 1 if pnl > 0 else 0, ds),
            )
        else:
            conn.execute(
                "INSERT INTO daily_summary VALUES (?, ?, 1, ?)",
                (ds, pnl, 1 if pnl > 0 else 0),
            )


def get_daily_summaries() -> list[dict]:
    """Return all daily summary rows for the calendar heatmap."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_summary ORDER BY trade_date"
        ).fetchall()
    return [dict(r) for r in rows]


def get_cumulative_pnl() -> list[dict]:
    """Return date + running cumulative P&L for the equity-curve chart."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT trade_date, total_pnl FROM daily_summary ORDER BY trade_date"
        ).fetchall()

    cumulative, result = 0.0, []
    for r in rows:
        cumulative += r["total_pnl"]
        result.append({"date": r["trade_date"], "cumulative_pnl": cumulative})
    return result


# ── System events ─────────────────────────────────────────────────────────────

def log_event(level: str, component: str, message: str) -> None:
    """
    Persist a system event (error, alert, etc.) to the audit trail.
    Timestamps are stored in US/Eastern so all audit rows align with
    market session times and are human-readable without offset conversion.
    """
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO system_events (ts, level, component, message) VALUES (?, ?, ?, ?)",
            (_now_et().isoformat(), level, component, message),
        )


# ── Aggregate statistics ───────────────────────────────────────────────────────

def get_statistics() -> dict:
    """
    Compute win rate, average win/loss, and max drawdown from closed trades.
    Called by the performance page on each refresh.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT realized_pnl FROM trades WHERE status = 'closed'"
        ).fetchall()

    if not rows:
        return {
            "total_trades": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "max_drawdown": 0.0, "total_pnl": 0.0,
        }

    pnls   = [r["realized_pnl"] for r in rows]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Max drawdown: largest peak-to-trough decline in cumulative equity
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(pnls),
        "win_rate":     len(wins) / len(pnls) if pnls else 0.0,
        "avg_win":      sum(wins)   / len(wins)   if wins   else 0.0,
        "avg_loss":     sum(losses) / len(losses) if losses else 0.0,
        "max_drawdown": max_dd,
        "total_pnl":    sum(pnls),
    }
