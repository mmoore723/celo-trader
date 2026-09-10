"""Compact sampled premium milestones; never submit or simulate broker orders."""
from datetime import timedelta
import json
import math

from database.connection import get_conn
from strategy_health.context_orb_exit import PREMIUM_PROTOCOLS, first_exit
from strategy_health.impulse_exit import et, executable_bid

CREATE_TABLE = '''CREATE TABLE IF NOT EXISTS research_premium_exit_paths (
    candidate_id TEXT PRIMARY KEY REFERENCES shadow_candidates(candidate_id),
    partial_bid REAL, partial_at TEXT, quote_count INTEGER NOT NULL DEFAULT 0,
    last_bid_at TEXT
)'''


def capture(row, frame, get_quote, clock):
    """Latch midpoint before quote I/O; retain runner and two-contract evidence."""
    identity=(row['candidate_id'],row['protocol'])
    now=et(clock())
    if row['status']=='collecting':
        event=first_exit(frame,entry_at=row['trigger_bar'],entry_quote_at=row['entry_quote_at'],
                         direction=row['direction'],meta=json.loads(row['metadata_json']),now=now,
                         strategy_id=next(key for key,value in PREMIUM_PROTOCOLS.items() if value==row['protocol']))
        if et(row['trigger_bar']).date()<now.date():
            event=(et(row['trigger_bar']).replace(hour=15,minute=55),'missed_session')
        if not math.isfinite(row['entry_ask']) or row['entry_ask']<=0:
            event=(et(row['trigger_bar']),'invalid_entry')
        if event:
            decision,reason=event
            if reason=='waiting_for_bars':
                return
            status='pending_quote' if reason in {'or_midpoint_close','eod_1555_cap'} else 'unmeasurable'
            with get_conn() as conn:
                conn.execute('''UPDATE research_strategy_exits SET status=?,decision_at=?,reason=?,detected_at=?
                    WHERE candidate_id=? AND protocol=? AND status='collecting' ''',
                    (status,decision.isoformat(),reason,now.isoformat(),*identity))
                row=dict(conn.execute('SELECT * FROM research_strategy_exits WHERE candidate_id=? AND protocol=?',identity).fetchone())
            if row['status'] not in {'collecting','pending_quote'}:
                return
    pending=row['status']=='pending_quote'
    # The original option replay allowed one minute to price the structural exit.
    if pending and now>et(row['decision_at'])+timedelta(minutes=1):
        with get_conn() as conn:
            conn.execute("UPDATE research_strategy_exits SET status='missing_quote' WHERE candidate_id=? AND protocol=? AND status='pending_quote'",identity)
        return
    quote,received=get_quote(row['contract_symbol'])
    if pending and et(received)>et(row['decision_at'])+timedelta(minutes=1):
        return
    decision=et(row['decision_at']) if pending else max(et(row['entry_quote_at']),et(received)-timedelta(seconds=60))
    priced=executable_bid(quote,contract=row['contract_symbol'],decision_at=decision,received_at=received)
    if not priced or et(priced[1])<=et(row['entry_quote_at']):
        return
    bid,stamp=priced
    with get_conn() as conn:
        conn.execute('INSERT OR IGNORE INTO research_premium_exit_paths(candidate_id) VALUES (?)',(identity[0],))
        path=dict(conn.execute('SELECT * FROM research_premium_exit_paths WHERE candidate_id=?',(identity[0],)).fetchone())
        if path['last_bid_at'] and et(stamp)<=et(path['last_bid_at']):
            return
        conn.execute('UPDATE research_premium_exit_paths SET quote_count=quote_count+1,last_bid_at=? WHERE candidate_id=?',(stamp,identity[0]))
        # No profit-target credit at or after a previously known structural exit.
        if not pending and bid+1e-9>=row['entry_ask']*1.30:
            conn.execute('UPDATE research_premium_exit_paths SET partial_bid=?,partial_at=? WHERE candidate_id=? AND partial_bid IS NULL',(bid,stamp,identity[0]))
        target=not pending and bid+1e-9>=row['entry_ask']*2
        if target or pending:
            conn.execute('''UPDATE research_strategy_exits SET status='priced',bid=?,bid_at=?,received_at=?,
                decision_at=COALESCE(decision_at,?),reason=COALESCE(reason,?),detected_at=COALESCE(detected_at,?)
                WHERE candidate_id=? AND protocol=? AND status IN ('collecting','pending_quote')''',
                (bid,stamp,et(received).isoformat(),stamp,'premium_target_100_pct',now.isoformat(),*identity))


def attach_paths(conn, exits, account, cutoff):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_premium_exit_paths'").fetchone():
        return
    for path in conn.execute('''SELECT p.* FROM research_premium_exit_paths p
        JOIN shadow_candidates s ON s.candidate_id=p.candidate_id
        WHERE COALESCE(s.broker_account_id,'')=? AND s.observed_at>=?''',(account or '',cutoff)):
        if path['candidate_id'] in exits:
            exits[path['candidate_id']]['premium_path']=dict(path)
