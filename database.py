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


@contextmanager
def _conn_for_mode(mode: str):
    """
    Yield a read connection to the DB file for the requested mode —
    regardless of which mode the bot is currently running in.

    get_conn() opens whichever DB matches the current bot setting.  That's
    correct for INSERT/UPDATE paths (the bot writes to its active DB).  But
    the Journal and Performance pages use a mode toggle: the user should be
    able to read paper trades while the bot is live and vice-versa.

    Bug without this: get_all_trades(mode="paper") while bot runs live →
    get_conn() opens trades_live.db → WHERE paper=1 → 0 rows always.

    Directory is derived from get_db_path().parent so it works whether the
    DB lives at the project root (single-user) or user_data/{id}/ (multi-user).
    """
    _db_dir  = get_db_path().parent
    _path    = _db_dir / f"trades_{mode}.db"
    # Auto-init schema if this DB file is new or was never migrated.
    # _init_db_at uses CREATE TABLE IF NOT EXISTS so it's safe to call every time.
    _init_db_at(_path)
    conn = sqlite3.connect(str(_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
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
    stop_price: Optional[float] = None,    # option premium stop-loss level at entry
    target_price: Optional[float] = None,  # Stage-1 target at entry
) -> int:
    """
    Insert an open trade.  Returns the new row id so we can update it on close.
    All timestamps stored as US/Eastern ISO strings for session-time alignment.
    """
    sql = """
        INSERT INTO trades
            (ticker, contract_symbol, option_type, strike, expiry,
             contracts, entry_price, entry_time, entry_reason,
             status, paper, strategy_id, stop_price, target_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (
            ticker, contract_symbol, option_type, strike, expiry,
            contracts, entry_price, _to_et_isoformat(entry_time), entry_reason,
            1 if paper else 0, strategy_id, stop_price, target_price,
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
    peak_price: Optional[float] = None,   # MFE: highest option mid-price seen during trade
    mae_price: Optional[float] = None,    # MAE: lowest  option mid-price seen during trade
    paper: bool = True,                   # False → deduct Alpaca commission from P&L
    recap: Optional[str] = None,          # Auto-generated trade recap stored in DB
) -> float:
    """
    Mark a trade closed and compute realised P&L.
    FIX N2: If confirmed_fill_price is provided (from broker fill confirmation),
    use that for P&L calculation instead of intended exit_price.
    peak_price / mae_price are the MFE and MAE values tracked live by position_manager.
    Commission ($0.65/contract × 2 legs) is deducted for live trades only.
    Returns the realised P&L in dollars (net of commissions on live).
    """
    from config import COMMISSION_PER_CONTRACT
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

        # Deduct round-trip commission on live trades (entry leg + exit leg).
        # Paper trading has no commissions — Alpaca paper is fee-free.
        if not paper:
            commission   = contracts * COMMISSION_PER_CONTRACT * 2
            realized_pnl = realized_pnl - commission
            logger.debug("Commission deducted: contracts=%d commission=$%.2f", contracts, commission)

        conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, exit_time = ?, exit_reason = ?,
                realized_pnl = ?, status = 'closed',
                peak_price = ?, mae_price = ?, recap = ?
            WHERE id = ?
            """,
            (actual_exit, _to_et_isoformat(exit_time), exit_reason,
             realized_pnl, peak_price, mae_price, recap, trade_id),
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


def get_all_trades(limit: int = 500, mode: str = "paper", status_filter: str = "all") -> list[dict]:
    """
    Return trades for the journal page.

    mode          — "paper" or "live". Opens the corresponding DB file directly
                    via _conn_for_mode() so the Journal's mode toggle always reads
                    the right database, regardless of which mode the bot is running.
    status_filter — "all" | "open" | "closed". Defaults to all.
    limit         — max rows returned.
    """
    if status_filter == "open":
        sql    = "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC LIMIT ?"
        params = (limit,)
    elif status_filter == "closed":
        sql    = "SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_time DESC LIMIT ?"
        params = (limit,)
    else:
        sql    = "SELECT * FROM trades ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT ?"
        params = (limit,)

    try:
        with _conn_for_mode(mode) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_all_trades(%s) failed: %s", mode, e)
        return []


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


def get_daily_summaries(mode: str = "paper") -> list[dict]:
    """
    Return daily P&L summary rows for the calendar heatmap.
    Opens the mode-specific DB directly so the Performance page's Paper/Live
    toggle always reads the right database.
    """
    try:
        with _conn_for_mode(mode) as conn:
            rows = conn.execute(
                """
                SELECT date(COALESCE(exit_time, entry_time)) AS trade_date,
                       SUM(COALESCE(realized_pnl, 0))        AS pnl,
                       COUNT(*)                              AS trades,
                       ROUND(
                         100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*), 0), 1
                       )                                     AS win_rate
                FROM trades
                WHERE status = 'closed'
                GROUP BY trade_date
                ORDER BY trade_date
                """,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_daily_summaries(%s) failed: %s", mode, e)
        return []


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
    Persist a system event to both:
      1. SQLite system_events table  (audit trail, Trade Journal)
      2. bot.log via Python logger   (THINKING panel in the dashboard)

    Previously log_event only wrote to SQLite, so all strategy decision
    messages ("No trade setup found", "Outside trading hours", entry/exit
    narratives, etc.) were invisible to the THINKING panel which reads bot.log.
    The dual-write here fixes that without changing any call sites.
    """
    # 1. Persist to SQLite
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO system_events (ts, level, component, message) VALUES (?, ?, ?, ?)",
            (_now_et().isoformat(), level, component, message),
        )

    # 2. Mirror to bot.log so WebSocket → THINKING panel can display it.
    # Use component as the logger name (e.g. "celo_trader.bar_eval") so the
    # frontend's network/thinking tab split works correctly — bar_eval and
    # trading_logic messages land in THINKING, not Network.
    import logging as _logging
    _evt_logger = _logging.getLogger(f"celo_trader.{component}")
    _lvl = level.upper()
    if _lvl == "ERROR":
        _evt_logger.error(message)
    elif _lvl in ("WARNING", "WARN"):
        _evt_logger.warning(message)
    else:
        _evt_logger.info(message)


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
