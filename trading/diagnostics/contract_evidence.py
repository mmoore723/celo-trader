"""Bounded contract-selection evidence. No orders or strategy mutation.

Selection snapshots are not fills. Poll samples are not a complete tick tape.
Missing/stale quotes and collection gaps stay visible for later validation.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import zlib

from auth.context import get_current_user_id
from config.paths import get_user_data_dir
from trading.diagnostics.native_coverage import PAIRS, warn

PROTOCOL = 'contract_selection_capture_v1'
MAX_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT = 512 * 1024
MAX_CHAIN_ROWS = 2000
MAX_WATCHES = 9
_lock = threading.Lock()


def clock():
    return datetime.now(timezone.utc)


def identity(settings):
    account = settings.get('active_broker_account_id')
    if not account or get_current_user_id() == 'system':
        return None
    if not isinstance(settings.get('paper_trading'), bool):
        return None
    raw = json.dumps([account, settings['paper_trading'], settings.get('broker_provider', 'alpaca')])
    return hashlib.sha256(raw.encode()).hexdigest()


def path():
    return get_user_data_dir(create=False) / 'contract_selection_evidence.sqlite3'


@contextmanager
def connect(target):
    target = Path(target)
    if target.is_symlink():
        raise ValueError('symlink_path')
    with _lock:
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        conn = sqlite3.connect(str(target), timeout=.05)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA journal_mode=DELETE')
            size = conn.execute('PRAGMA page_size').fetchone()[0]
            conn.execute(f'PRAGMA max_page_count={MAX_BYTES // size}')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS selections (
                    account TEXT NOT NULL, candidate TEXT NOT NULL, cohort TEXT NOT NULL,
                    observed TEXT NOT NULL, session TEXT NOT NULL, payload BLOB NOT NULL,
                    digest TEXT NOT NULL, PRIMARY KEY(account,candidate,cohort));
                CREATE TABLE IF NOT EXISTS watches (
                    account TEXT NOT NULL, session TEXT NOT NULL, symbol TEXT NOT NULL,
                    PRIMARY KEY(account,session,symbol));
                CREATE TABLE IF NOT EXISTS quotes (
                    account TEXT NOT NULL, session TEXT NOT NULL, symbol TEXT NOT NULL,
                    minute TEXT NOT NULL, observed TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(account,session,symbol,minute));
            ''')
            if conn.execute('PRAGMA page_count').fetchone()[0] * size > MAX_BYTES - 1024 * 1024:
                raise ValueError('contract_storage_budget_reached')
            yield conn
            conn.commit()
        finally:
            conn.close()


class TraceReader:
    """Copy existing selector reads without changing returned data or requests."""
    def __init__(self, reader):
        self.reader = reader
        self.chains = []
        self.expirations = []
        self.started = clock().isoformat()
        self.overflow = False

    def get_expirations(self, *args, **kwargs):
        result = self.reader.get_expirations(*args, **kwargs)
        try:
            self.expirations = deepcopy(result)
        except Exception:
            self.overflow = True
        return result

    def get_option_chain(self, ticker, expiry, option_type):
        result = self.reader.get_option_chain(ticker, expiry, option_type)
        try:
            if sum(len(c['rows']) for c in self.chains) + len(result or []) > MAX_CHAIN_ROWS:
                self.overflow = True
            elif not self.overflow:
                self.chains.append(dict(expiry=expiry, option_type=option_type,
                                        received_at=clock().isoformat(), rows=deepcopy(result or [])))
        except Exception:
            self.overflow = True
        return result


def _time(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp_without_timezone')
    return parsed


def quote_issues(quote, observed):
    """Strict quote validity, not proof that displayed size would fill an order."""
    issues = []
    for field in ('bid', 'ask', 'bidsize', 'asksize'):
        value = quote.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            issues.append('missing_or_invalid_' + field)
    if not issues and quote['ask'] < quote['bid']:
        issues.append('crossed_quote')
    for field in ('bid_date', 'ask_date'):
        try:
            age = (observed - _time(quote.get(field))).total_seconds()
            if not 0 <= age <= 60:
                issues.append('stale_or_future_' + field)
        except (ValueError, TypeError, OverflowError, OSError):
            issues.append('missing_or_invalid_' + field)
    return issues


def delta_watch(trace, *, strategy_id, ticker, direction, price, maximum, now):
    """Subscribe the declared .50-delta candidate without qualifying its data.

    This is only a watch subscription, never an execution selection. Preserve
    the raw Greek timestamp so subsequent analysis can reject stale/ambiguous
    inputs. Missing Greeks never become zero-delta candidates.
    """
    from zoneinfo import ZoneInfo
    from trading.entry.contract import reviewed_contract_profile
    profile = reviewed_contract_profile(strategy_id, ticker)
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    candidates = []
    for chain in trace.chains if not trace.overflow else []:
        try:
            dte = (datetime.fromisoformat(chain['expiry']).date() - today).days
        except (TypeError, ValueError):
            continue
        if not profile.minimum_dte <= dte <= profile.maximum_dte:
            continue
        for row in chain['rows']:
            raw = row.get('evidence') or {}
            greek = raw.get('greeks') or {}
            delta = greek.get('delta')
            try:
                bid, ask, strike = (float(row[k]) for k in ('bid', 'ask', 'strike'))
                valid_delta = isinstance(delta, (int, float)) and math.isfinite(delta) and abs(delta) <= 1
                if (not valid_delta or not all(math.isfinite(v) for v in (bid, ask, strike))
                        or bid <= 0 or ask < bid or ask*100 > maximum
                        or not profile.minimum_premium <= ask <= profile.maximum_premium
                        or (ask-bid)/((ask+bid)/2) > profile.maximum_spread_pct
                        or not (strike > price if direction == 'bullish' else strike < price)
                        or not row.get('symbol')):
                    continue
                candidates.append((abs(abs(delta)-.5), dte, abs(strike-price), row['symbol'], greek))
            except (KeyError, ValueError, TypeError, ZeroDivisionError):
                continue
    if not candidates:
        return None
    winner = min(candidates, key=lambda r: r[:4])
    return dict(symbol=winner[3], raw_greeks=winner[4], timestamp_validated=False,
                purpose='watch_only_pending_timestamp_validation')


def record(*, trace, settings, candidate_id, strategy_id, ticker, version,
           direction, price, maximum, contract, info, cohort, trigger=None, target=None):
    account = identity(settings)
    if not account or ticker not in PAIRS.get(strategy_id, ()) or not candidate_id:
        return False
    now = clock()
    from zoneinfo import ZoneInfo
    session = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    winners = deepcopy(info.get('shadow_contract_leaderboard') or [])
    symbols = {r['symbol'] for r in winners if r.get('symbol')}
    if contract:
        symbols.add(contract['symbol'])
    delta = delta_watch(trace, strategy_id=strategy_id, ticker=ticker, direction=direction,
                        price=price, maximum=maximum, now=now)
    if delta:
        symbols.add(delta['symbol'])
    # Delta is retained as source evidence, not silently used without an
    # independently verified Greek timestamp/timezone. All chains remain saved.
    payload = dict(protocol=PROTOCOL, strategy_id=strategy_id, ticker=ticker,
        strategy_version=version, direction=direction, underlying_price=price,
        maximum_contract_dollars=maximum, cohort=cohort, trigger=str(trigger),
        selection_started=trace.started, selection_finished=now.isoformat(),
        expirations=trace.expirations, chains=trace.chains if not trace.overflow else [],
        coverage='chain_budget_exceeded' if trace.overflow else 'selection_snapshot',
        control=contract, selection=info, native_fill_confirmed=False,
        delta_ranking_status='requires_verified_greek_timestamp', delta_watch=delta,
        path_semantics='observed_quote_samples_not_complete_tick_tape')
    if len(symbols) > MAX_WATCHES:
        raise ValueError('contract_watch_budget')
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_SNAPSHOT:
        raise ValueError('contract_snapshot_budget')
    with connect(target or path()) as conn:
        cursor = conn.execute('INSERT OR IGNORE INTO selections VALUES (?,?,?,?,?,?,?)',
            (account, candidate_id, cohort, now.isoformat(), session, zlib.compress(raw),
             hashlib.sha256(raw).hexdigest()))
        if cursor.rowcount:
            conn.executemany('INSERT OR IGNORE INTO watches VALUES (?,?,?)',
                             [(account, session, s) for s in sorted(symbols)])
        return bool(cursor.rowcount)


def capture(*, reader, settings, stopped=lambda: False, now=None, target=None):
    """At most three batch reads per checkpoint. Persist misses; no backfill.

    Oldest-observed watches get priority, including across restarts. All plays
    share one quote per symbol/minute, rather than one request per strategy.
    Watches stay through 16:05 ET to retain session exit context. Early closes
    and missing passes remain evident from actual timestamps, never filled in.
    """
    from zoneinfo import ZoneInfo
    account = identity(settings)
    target = Path(target or path())
    if not account or not target.exists() or stopped():
        return 0
    now = now or clock()
    local = now.astimezone(ZoneInfo('America/New_York'))
    if local.weekday() >= 5 or not (9, 30) <= (local.hour, local.minute) <= (16, 5):
        return 0
    session, minute = local.date().isoformat(), now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M')
    with connect(target) as conn:
        rows = conn.execute('''SELECT w.symbol, MAX(q.observed) AS latest FROM watches w
            LEFT JOIN quotes q ON q.account=w.account AND q.session=w.session AND q.symbol=w.symbol
            WHERE w.account=? AND w.session=?
            GROUP BY w.symbol HAVING MAX(q.minute) IS NULL OR MAX(q.minute)<?
            ORDER BY latest, w.symbol LIMIT 300''', (account, session, minute)).fetchall()
    count = 0
    for start in range(0, len(rows), 100):
        if stopped():
            break
        symbols = [r['symbol'] for r in rows[start:start+100]]
        error = None
        try:
            found = reader.get_research_option_quotes(symbols)
        except Exception:
            found, error = {}, 'batch_read_failed'
        received = clock()
        with connect(target) as conn:
            for symbol in symbols:
                quote = found.get(symbol) or {}
                issues = [error or 'quote_missing'] if not quote else quote_issues(quote, received)
                if quote and quote.get('symbol') != symbol:
                    issues.append('wrong_symbol')
                payload = json.dumps(dict(quote=quote, issues=issues, requested_at=now.isoformat()), allow_nan=False)
                conn.execute('INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?,?)',
                    (account, session, symbol, minute, received.isoformat(), payload))
                count += 1
    return count


def safe_capture(**kwargs):
    try:
        return capture(**kwargs)
    except Exception as exc:
        warn('contract_capture_' + type(exc).__name__)
        return 0


def observe_research(*, signal, ticker, price, reader, settings, stopped=lambda: False):
    """Native contract rules on explicitly separate research entry cohorts.

    Never promote expanded research signals to native execution evidence.
    Their exact version and candidate ID remain attached to the snapshot.
    """
    from config.research_snapshot import current_snapshot
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from trading.research_versions import capture_versions
    from trading.entry.contract import select_reviewed_v2_contract
    pinned = current_snapshot(get_current_user_id())
    account = identity(settings)
    sid = getattr(signal, 'strategy_id', None)
    meta = getattr(signal, 'meta', None)
    if (not pinned or not account or identity(pinned) != account or stopped()
            or not pinned.get('shadow_ledger_enabled', True)
            or ticker not in PAIRS.get(sid, ()) or not isinstance(meta, dict)
            or meta.get('research_existing_candidate') or not meta.get('shadow_candidate_id')):
        return
    if meta.get('strategy_version') not in capture_versions(sid, REVIEWED_STRATEGIES[sid].version):
        return
    candidate = meta['shadow_candidate_id']
    with connect(path()) as conn:
        if conn.execute('SELECT 1 FROM selections WHERE account=? AND candidate=? AND cohort=?',
                        (account, candidate, 'research_native_contract_rules')).fetchone():
            return
    trace = TraceReader(reader)
    try:
        contract, info = select_reviewed_v2_contract(trace, ticker, signal.direction, price,
            1000.0, for_display=True, strategy_id=sid)
    except Exception:
        contract, info = None, {'reason': 'selection_read_failed'}
    if not stopped():
        record(trace=trace, settings=settings, candidate_id=candidate, strategy_id=sid,
               ticker=ticker, version=meta.get('strategy_version'), direction=signal.direction,
               price=price, maximum=1000.0, contract=contract, info=info,
               cohort='research_native_contract_rules', trigger=getattr(signal, 'trigger_bar', None))
