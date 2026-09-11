"""Study ledger. Caller supplies the explicitly scoped user/mode DB.

Only this study table is written. Primary candidates, quotes, exits, and user
settings remain unchanged. The research worker pins account and mode for each pass.
"""
from copy import deepcopy
import json

from strategy_health.impulse_exit import et
from trading.expiration_study_selection import PROFILE
from strategy_health.expiration_study_exits import initialize, advance, ACTIVE, TIMED

TABLE = 'research_expiration_comparisons'
CREATE_TABLE = '''CREATE TABLE IF NOT EXISTS research_expiration_comparisons (
    candidate_id TEXT NOT NULL REFERENCES shadow_candidates(candidate_id),
    profile_version TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    active INTEGER NOT NULL,
    PRIMARY KEY(candidate_id, profile_version)
)'''
CREATE_INDEX = '''CREATE INDEX IF NOT EXISTS idx_expiration_comparisons_active
    ON research_expiration_comparisons(profile_version, active)'''


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


def record(conn, *, account, candidate_id, selection):
    """First observation wins, including a failed selection. No retry/repricing."""
    row = conn.execute('''SELECT * FROM shadow_candidates WHERE candidate_id=?
        AND COALESCE(broker_account_id,'')=?''', (candidate_id, account or '')).fetchone()
    if row is None:
        return False
    if et(selection['setup_at']) != et(row['observed_at']):
        raise ValueError('Study selection must belong to the original setup time')
    if selection.get('contract'):
        entry = et(selection['contract']['entry_quote_at'])
        if not 0 <= (entry-et(row['observed_at'])).total_seconds() <= 60:
            raise ValueError('Cannot enroll a late/repriced entry')
    state = initialize(strategy_id=row['strategy_id'], direction=row['direction'],
                       trigger_bar=row['trigger_bar'], meta=json.loads(row['metadata_json']), selection=selection)
    result = conn.execute('''INSERT OR IGNORE INTO research_expiration_comparisons
        (candidate_id,profile_version,selection_json,state_json,active) VALUES (?,?,?,?,?)''',
        (candidate_id, PROFILE, encoded(selection), encoded(state), int(state['status'] in ACTIVE)))
    return bool(result.rowcount)


def load(conn, *, account, active_only=False, cutoff=None):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return []
    rows = conn.execute('''SELECT e.*,s.ticker FROM research_expiration_comparisons e
        JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
        WHERE e.profile_version=? AND COALESCE(s.broker_account_id,'')=?'''
        + (' AND e.active=1' if active_only else '')
        + (' AND s.observed_at>=?' if cutoff else '') + ' ORDER BY s.observed_at,s.candidate_id',
        (PROFILE, account or '') + ((cutoff,) if cutoff else ()))
    return [dict(row, state=json.loads(row['state_json']), selection=json.loads(row['selection_json'])) for row in rows]


def save_transition(conn, *, account, row, state):
    """CAS protects a latched exit against stale/concurrent polls or restart."""
    before = row['state']
    frozen = ('profile_version','strategy_id','strategy_version','protocol','direction',
              'trigger_bar','meta','contract_symbol','entry_ask','entry_quote_at')
    if any(state.get(key) != before.get(key) for key in frozen):
        raise ValueError('Cannot rewrite the study identity or entry')
    if before['status'] not in ACTIVE and state != before:
        raise ValueError('Cannot replace a terminal study result')
    transitions = {'collecting': {'collecting', 'pending_quote', 'priced', 'missing_quote', 'unmeasurable'},
                   'pending_quote': {'pending_quote', 'priced', 'missing_quote'}}
    if before['status'] in ACTIVE and state['status'] not in transitions[before['status']]:
        raise ValueError('Invalid exit-state transition')
    if before.get('decision_at') and any(state.get(key) != before.get(key) for key in ('decision_at','reason','detected_at')):
        raise ValueError('Cannot replace the first exit decision')
    result = conn.execute('''UPDATE research_expiration_comparisons SET state_json=?,active=?
        WHERE candidate_id=? AND profile_version=? AND state_json=?
        AND EXISTS (SELECT 1 FROM shadow_candidates s WHERE s.candidate_id=research_expiration_comparisons.candidate_id
        AND COALESCE(s.broker_account_id,'')=?)''',
        (encoded(deepcopy(state)), int(state['status'] in ACTIVE), row['candidate_id'], PROFILE,
         row['state_json'], account or ''))
    return bool(result.rowcount)


def capture(*, connect, account, bars_lookup, quote_lookup, clock, stopped=lambda: False,
            ema_bars_lookup=None):
    """Latch first, share reads, and price the exact contract.

    The caller must bind connect to a fixed user/mode database for the entire
    pass. Pending exits have priority; repeated overlapping plays share reads,
    but every play retains its own entry, decision and result.
    """
    from strategy_health import context_orb_exit, squeeze_exit, ema_exit
    from trading.research_ema_history import NATIVE_POLICY
    if stopped():
        return dict(rows=0, bars_reads=0, quote_reads=0, failed_rows=0)
    with connect() as conn:
        rows = load(conn, account=account, active_only=True)
    rows.sort(key=lambda r: r['state']['status'] != 'pending_quote')
    stats = dict(rows=0, bars_reads=0, quote_reads=0, failed_rows=0)
    frames, quotes = {}, {}
    for row in rows:
        if stopped():
            break
        stats['rows'] += 1
        try:
            state = row['state']
            sid = state['strategy_id']
            frame = None
            if state['status'] == 'collecting' and sid not in TIMED:
                native = sid == ema_exit.STRATEGY_ID and state['meta'].get('history_policy') == NATIVE_POLICY
                key = (row['ticker'], 'native15' if native else '1min')
                if key not in frames:
                    frames[key] = None
                    reader = ema_bars_lookup if native else bars_lookup
                    if reader is not None:
                        stats['bars_reads'] += 1
                        frames[key] = reader(row['ticker'])
                frame = frames[key]
            advanced = advance(state, frame=frame, now=clock())
            if advanced != state:
                with connect() as conn:
                    if not save_transition(conn, account=account, row=row, state=advanced):
                        continue
                row = {**row, 'state': advanced, 'state_json': encoded(advanced)}
            state = advanced
            premium = sid in context_orb_exit.PREMIUM_PROTOCOLS or sid == squeeze_exit.STRATEGY_ID
            if state['status'] != 'pending_quote' and not (premium and state['status'] == 'collecting'):
                continue
            if stopped():
                break
            symbol = state['contract_symbol']
            if symbol not in quotes:
                quotes[symbol] = (None, clock())
                stats['quote_reads'] += 1
                quotes[symbol] = (quote_lookup(symbol), clock())
            quote, received = quotes[symbol]
            priced = advance(state, frame=frame, now=received, quote=quote)
            if priced != state:
                with connect() as conn:
                    save_transition(conn, account=account, row=row, state=priced)
        except Exception:
            # A provider fault cannot erase the previously committed decision.
            # No quotes/errors are persisted as a zero-price fill.
            stats['failed_rows'] += 1
    return stats
