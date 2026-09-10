"""One bounded state row per new research play; shared reads, no order access."""
from datetime import timedelta
import json
import logging

from database.connection import get_conn
from database.helpers import _now_et
from strategy_health.option_profit_protection import PROTOCOL_BY_STRATEGY, RECOVERY_PROTOCOL, VERSION_BY_STRATEGY, MINUTES_BY_STRATEGY, initialize, advance
from strategy_health.recovery_profit_protection import freeze, observe_target, can_arm
from strategy_health.impulse_exit import et
from database.reference_contract_tests import load as load_reference_tests, TABLE as REFERENCE_TABLE

logger = logging.getLogger('celo_trader.research')
CREATE_TABLE = '''CREATE TABLE IF NOT EXISTS research_option_profit_tests (
    candidate_id TEXT PRIMARY KEY REFERENCES shadow_candidates(candidate_id),
    protocol TEXT NOT NULL, contract_symbol TEXT NOT NULL,
    entry_ask REAL NOT NULL, entry_quote_at TEXT NOT NULL,
    state_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
)'''
CREATE_INDEX = 'CREATE INDEX IF NOT EXISTS idx_option_profit_active ON research_option_profit_tests(active)'


def capture(*, account, quote_lookup, bars_lookup=None, stopped=lambda: False, clock=_now_et):
    if stopped():
        return
    with get_conn() as conn:
        for strategy_id, protocol in PROTOCOL_BY_STRATEGY.items():
            new = conn.execute('''SELECT s.candidate_id,s.direction,s.metadata_json,q.contract_symbol,q.ask,q.bid,q.observed_at
            FROM shadow_candidates s JOIN candidate_option_quote_observations q ON q.candidate_id=s.candidate_id
            LEFT JOIN research_option_profit_tests e ON e.candidate_id=s.candidate_id
            WHERE e.candidate_id IS NULL AND s.strategy_id=? AND COALESCE(s.broker_account_id,'')=?
            AND s.observed_at>=? AND q.observation_kind='entry' AND q.source='tradier_research_contract_v1'
            AND q.ask>0 AND q.bid>=0 AND q.bid<=q.ask
            AND json_valid(s.metadata_json) AND json_extract(s.metadata_json,'$.profit_protection_protocol')=?
            AND json_extract(s.metadata_json,'$.strategy_version')=?''',
                (strategy_id, account or '', (et(clock())-timedelta(days=2)).date().isoformat(), protocol, VERSION_BY_STRATEGY[strategy_id])).fetchall()
            for row in new:
                state = initialize(row['observed_at'], row['ask'], row['bid'], minutes=MINUTES_BY_STRATEGY[strategy_id])
                if protocol == RECOVERY_PROTOCOL:
                    state = freeze(state, json.loads(row['metadata_json']), row['direction'])
                conn.execute('INSERT OR IGNORE INTO research_option_profit_tests VALUES (?,?,?,?,?,?,1)',
                             (row['candidate_id'], protocol, row['contract_symbol'], row['ask'], row['observed_at'], json.dumps(state)))
        rows = [dict(r) for r in conn.execute('''SELECT e.*,s.ticker,s.strategy_id FROM research_option_profit_tests e
            JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
            WHERE e.active=1 AND COALESCE(s.broker_account_id,'')=?''', (account or '',))
                if PROTOCOL_BY_STRATEGY.get(r['strategy_id']) == r['protocol']]
        for row in rows:
            row['_table'] = 'research_option_profit_tests'
            row['minutes'] = MINUTES_BY_STRATEGY[row['strategy_id']]
        rows.extend(dict(r, _table=REFERENCE_TABLE)
                    for r in load_reference_tests(conn, account, active_only=True).values())
    quotes, frames = {}, {}
    for row in rows:
        if stopped():
            return
        try:
            before = json.loads(row['state_json'])
            args = dict(entry_at=row['entry_quote_at'], ask=row['entry_ask'], contract=row['contract_symbol'],
                        minutes=row.get('minutes', 30))
            state = before
            recovery = row['protocol'] == RECOVERY_PROTOCOL
            if recovery and state['trail']['status'] == 'collecting' and not state.get('target_detected_at'):
                ticker = row['ticker']
                if ticker not in frames:
                    frames[ticker] = []
                    if bars_lookup:
                        try:
                            frame = bars_lookup(ticker)
                            frames[ticker] = frame.to_dict('records') if hasattr(frame,'to_dict') else list(frame or [])
                        except Exception:
                            logger.warning('Recovery candle lookup unavailable; evidence remains missing')
                state = observe_target(state, frames[ticker], entry_at=row['entry_quote_at'], now=clock())
            state = advance(state, now=clock(), allow_arm=not recovery, **args)
            # Once the trail ends, only the due control needs another quote.
            if state['trail']['status'] in {'collecting','pending_quote'} or state['control']['status'] == 'pending_quote':
                symbol = row['contract_symbol']
                if symbol not in quotes:
                    quotes[symbol] = (None, clock())  # Do not retry failures for each overlapping play.
                    try:
                        quotes[symbol] = (quote_lookup(symbol), clock())
                    except Exception:
                        logger.warning('Profit-protection quote unavailable; evidence remains missing')
                quote, received = quotes[symbol]
                state = advance(state, now=received, quote=quote,
                                allow_arm=not recovery or can_arm(state,quote,received), **args)
            active = int(any(state[k]['status'] in {'collecting', 'pending_quote'} for k in ('control', 'trail')))
            encoded = json.dumps(state, sort_keys=True)
            if encoded != row['state_json'] or not active:
                with get_conn() as conn:
                    # A stale/concurrent poll cannot overwrite a latched decision.
                    # Table identifiers are module constants, never external input.
                    table = row['_table']
                    extra = ' AND profile_version=?' if table == REFERENCE_TABLE else ''
                    values = (encoded, active, row['candidate_id'], row['protocol'], row['state_json'])
                    if extra:
                        values += (row['profile_version'],)
                    conn.execute(f'''UPDATE {table} SET state_json=?,active=?
                        WHERE candidate_id=? AND protocol=? AND state_json=?''' + extra, values)
        except Exception:
            logger.warning('Profit-protection capture failed candidate=%s', row['candidate_id'], exc_info=True)


def load(conn, account, cutoff):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_option_profit_tests'").fetchone():
        return {}
    return {r['candidate_id']: dict(r, state=json.loads(r['state_json'])) for r in conn.execute('''
        SELECT e.*,s.strategy_id FROM research_option_profit_tests e JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
        WHERE s.observed_at>=? AND COALESCE(s.broker_account_id,'')=?''', (cutoff, account or ''))
        if PROTOCOL_BY_STRATEGY.get(r['strategy_id']) == r['protocol']}
