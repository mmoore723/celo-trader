"""Read-only cross-user journal. No broker requests or trading context switches."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from api.routes.trades import _row_to_trade, _strategy_version_from_trade_row


def strategy_name(value):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule = REVIEWED_STRATEGIES.get(value)
    return rule.display_name if rule else str(value or '').replace('_', ' ')


def entry_epoch(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo('America/New_York'))).timestamp()
    except (ValueError, TypeError):
        return 0


def read_journal(root: Path, *, user_id='', mode='all', status='all', ticker='', strategy='', offset=0, limit=50):
    root = root.resolve()
    names = {}
    users_db = root / 'users.db'
    if users_db.is_file() and not users_db.is_symlink():
        with closing(sqlite3.connect(users_db.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
            names = dict(db.execute('SELECT id,username FROM users'))
    owners = []; rows = []; total = 0; warnings = []
    for directory in sorted(root.iterdir()) if root.is_dir() else []:
        if not directory.is_dir() or directory.is_symlink():
            continue
        uid = directory.name
        if uid not in names and not any((directory/f'trades_{m}.db').is_file() for m in ('paper','live')):
            continue
        if uid not in names:
            # Empty leftover databases are not user accounts. Keep nonempty or
            # unreadable retained journals discoverable without inventing identity.
            has_records = False
            for m in ('paper','live'):
                f = directory/f'trades_{m}.db'
                if not f.is_file() or f.is_symlink(): continue
                try:
                    with closing(sqlite3.connect(f.as_uri()+'?mode=ro',uri=True,timeout=.2)) as db:
                        has_records |= db.execute('SELECT 1 FROM trades LIMIT 1').fetchone() is not None
                except sqlite3.Error:
                    has_records = True
            if not has_records: continue
        label = names.get(uid, 'System records (owner unverified)' if uid == 'system' else f'Unlinked records ({uid})')
        owner = {'user_id': uid, 'username': label, 'retained_user': uid not in names}
        owners.append(owner)
        if user_id and uid != user_id:
            continue
        for trade_mode in ('paper', 'live') if mode == 'all' else (mode,):
            path = directory / f'trades_{trade_mode}.db'
            if not path.is_file():
                continue
            if path.is_symlink():
                warnings.append(f'{owner["username"]} ({trade_mode}): journal path unavailable')
                continue
            try:
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
                    db.row_factory = sqlite3.Row
                    started = time.monotonic()
                    db.set_progress_handler(lambda: int(time.monotonic()-started > 2), 1000)
                    db.create_function('journal_epoch', 1, entry_epoch, deterministic=True)
                    db.create_function('strategy_name', 1, strategy_name, deterministic=True)
                    clauses=[]; params=[]
                    if status != 'all': clauses.append('status=?'); params.append(status)
                    if ticker: clauses.append('ticker=?'); params.append(ticker.upper())
                    if strategy.strip():
                        clauses.append("instr(lower(replace(COALESCE(strategy_id,'') || ' ' || strategy_name(strategy_id),'_',' ')),?)>0")
                        params.append(strategy.strip().lower().replace('_',' '))
                    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
                    count = db.execute('SELECT count(*) FROM trades'+where, params).fetchone()[0]
                    batch = db.execute('SELECT * FROM trades'+where+' ORDER BY journal_epoch(entry_time) DESC,id DESC LIMIT ?',
                                       [*params, offset+limit]).fetchall()
                    total += count
                    for raw in batch:
                        row = dict(raw)
                        # File mode is authoritative. Never silently relabel inconsistent rows.
                        if row.get('paper') is not None and bool(row['paper']) != (trade_mode == 'paper'):
                            row['mode_warning'] = 'Recorded mode disagrees with journal file'
                        row['paper'] = int(trade_mode == 'paper')
                        rows.append((entry_epoch(row.get('entry_time')), uid, trade_mode, row, owner))
            except sqlite3.Error:
                warnings.append(f'{owner["username"]} ({trade_mode}): journal could not be read; retry refresh')
    rows.sort(key=lambda r: (r[0], r[1], r[2], int(r[3]['id'])), reverse=True)
    result=[]
    for _, uid, trade_mode, row, owner in rows[offset:offset+limit]:
        try:
            trade = _row_to_trade(row).model_dump()
            trade.update(owner)
            trade.update({k: row.get(k) for k in ('broker_account_id','entry_reason','parent_trade_id',
                          'entry_order_id','exit_order_id','entry_fill_time','exit_fill_time','mode_warning')})
            trade['strategy_version'] = _strategy_version_from_trade_row(row)
            trade['strategy_name'] = strategy_name(row.get('strategy_id'))
            trade['journal_key'] = f'{uid}:{trade_mode}:{row["id"]}'
            result.append(trade)
        except (ValueError, TypeError):
            warnings.append(f'{owner["username"]} ({trade_mode}) trade {row["id"]}: invalid saved fields')
    return {'trades':result, 'users':owners, 'total':total, 'offset':offset, 'limit':limit,
            'has_more':offset+limit<total, 'warnings':warnings}
