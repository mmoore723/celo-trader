"""Separate, bounded reviewed-contract evidence; never rewrites primary quotes."""
from collections import Counter
import json

from config.strategy_catalog import REVIEWED_STRATEGIES
from database.connection import get_conn
from strategy_health.impulse_exit import et
from strategy_health.option_profit_protection import (
    PROTOCOL_BY_STRATEGY, RECOVERY_PROTOCOL, ORB_STRATEGY_ID, initialize, summary as profit_summary,
)
from strategy_health.recovery_profit_protection import freeze
from trading.research_versions import capture_versions

PROFILE = 'reviewed_contract_reference_v1'
# Freeze current versions/horizons, so future edits cannot inherit this proof.
STRATEGIES = {
    'V2_ORB_PULLBACK': ('2.0.0', 90),
    'V2_SPY_TREND_CONT': ('2.1.0', 30),
    'V2_SPY_AFTERNOON_FVG': ('2.1.0', 30),
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': ('2.1.0', 30),
    'V2_TSLA_TWO_LEG_TREND_PULLBACK': ('2.1.0', 90),
}
TABLE = 'research_reference_contract_tests'
CREATE_TABLE = '''CREATE TABLE IF NOT EXISTS research_reference_contract_tests (
    candidate_id TEXT NOT NULL REFERENCES shadow_candidates(candidate_id),
    profile_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
    protocol TEXT NOT NULL, minutes INTEGER NOT NULL,
    contract_symbol TEXT, entry_ask REAL, entry_quote_at TEXT NOT NULL,
    details_json TEXT NOT NULL, state_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(candidate_id,profile_version)
)'''
CREATE_INDEX = 'CREATE INDEX IF NOT EXISTS idx_reference_contract_active ON research_reference_contract_tests(active)'


def record(*, candidate_id, strategy_id, direction, meta, contract, observed_at, details):
    version, minutes = STRATEGIES[strategy_id]
    if meta.get('strategy_version') not in capture_versions(strategy_id,version) or REVIEWED_STRATEGIES[strategy_id].version != version:
        return
    version = meta['strategy_version']
    protocol = PROTOCOL_BY_STRATEGY.get(strategy_id, f'reference_fixed_{minutes}m_v1')
    started = et(observed_at).isoformat()
    state = initialize(started, contract['ask'], contract['bid'], minutes=minutes) if contract else dict(
        control={'status': 'no_contract'}, trail={'status': 'not_tested'})
    if contract:
        from strategy_health.initial_loss_protection import attach
        state = attach(state, strategy_id=strategy_id, meta=meta, entry_at=started,
                       ask=contract['ask'], bid=contract['bid'], minutes=minutes)
    if protocol == RECOVERY_PROTOCOL and contract:
        state = freeze(state, meta, direction)
    if strategy_id not in PROTOCOL_BY_STRATEGY:
        state['trail'] = {'status': 'not_tested'}
    with get_conn() as conn:
        candidate = conn.execute('SELECT strategy_id,direction,observed_at FROM shadow_candidates WHERE candidate_id=?',
                                 (candidate_id,)).fetchone()
        if not candidate or candidate['strategy_id'] != strategy_id or candidate['direction'] != direction:
            return
        if not 0 <= (et(started)-et(candidate['observed_at'])).total_seconds() <= 90:
            for key in ('control', 'trail'):
                if state[key]['status'] == 'collecting':
                    state[key] = {'status': 'invalid_entry', 'reason': 'entry_selection_delayed'}
            # No new experiment may bypass the reference entry timing gate.
            state.pop('initial_loss_test', None)
        active = int(any(state[k]['status'] == 'collecting' for k in ('control', 'trail')))
        conn.execute('''INSERT OR IGNORE INTO research_reference_contract_tests
            (candidate_id,profile_version,strategy_version,protocol,minutes,contract_symbol,
             entry_ask,entry_quote_at,details_json,state_json,active) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (candidate_id, PROFILE, version, protocol, minutes, contract.get('symbol') if contract else None,
             contract['ask'] if contract else None, started, json.dumps(details), json.dumps(state), active))


def load(conn, account, cutoff=None, *, active_only=False):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return {}
    clauses = ['e.profile_version=?', "COALESCE(s.broker_account_id,'')=?"]
    params = [PROFILE, account or '']
    if cutoff is not None:
        clauses.append('s.observed_at>=?'); params.append(cutoff)
    if active_only:
        clauses.append('e.active=1')
    rows = conn.execute('''SELECT e.*,s.strategy_id,s.ticker FROM research_reference_contract_tests e
        JOIN shadow_candidates s ON s.candidate_id=e.candidate_id WHERE '''+' AND '.join(clauses), params)
    result = {}
    for row in rows:
        sid = row['strategy_id']
        allowed_protocols = {PROTOCOL_BY_STRATEGY.get(sid, f"reference_fixed_{row['minutes']}m_v1")}
        # Pre-trail ORB controls remain visible and finish on their original
        # protocol. Never turn their historical path into a new trail sample.
        if sid == ORB_STRATEGY_ID:
            allowed_protocols.add('reference_fixed_90m_v1')
        if (sid not in STRATEGIES or row['minutes'] != STRATEGIES[sid][1]
                or row['strategy_version'] not in capture_versions(sid,STRATEGIES[sid][0])
                or REVIEWED_STRATEGIES[sid].version != STRATEGIES[sid][0]
                or row['protocol'] not in allowed_protocols):
            continue
        result[row['candidate_id']] = dict(row, state=json.loads(row['state_json']))
    return result


def summary(samples, rows, strategy_id):
    from strategy_health.authored_exit_summary import net_profit
    from strategy_health.exit_comparison import totals
    if strategy_id not in STRATEGIES:
        return None
    selected = [rows[s['candidate_id']] for s in samples if s['candidate_id'] in rows
                and rows[s['candidate_id']]['strategy_id'] == strategy_id]
    controls, days = [], set()
    for row in selected:
        control = dict({k: row[k] for k in ('candidate_id', 'contract_symbol', 'entry_ask', 'entry_quote_at')},
                       **row['state']['control'])
        if net_profit(control) is not None:
            controls.append(control); days.add(et(row['entry_quote_at']).date().isoformat())
    return dict(profile_version=PROFILE, minutes=STRATEGIES[strategy_id][1],
                tracked=len(selected), selected=sum(bool(r['contract_symbol']) for r in selected),
                first_test_at=min((r['entry_quote_at'] for r in selected), default=None),
                option_results=len(controls), result_days=len(days), control=totals(controls),
                statuses=dict(Counter(r['state']['control']['status'] for r in selected)),
                selection_reasons=dict(Counter(json.loads(r['details_json'])['reason'] for r in selected)),
                profit_protection=(profit_summary(samples, {r['candidate_id']: r for r in selected if r['contract_symbol']}, strategy_id)
                                   if strategy_id in PROTOCOL_BY_STRATEGY else None))
