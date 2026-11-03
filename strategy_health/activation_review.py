"""Evidence-bound implementation approvals. Never grants order authority."""
from dataclasses import asdict, is_dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3


def _scope(settings):
    from config import get_db_path
    return sha256(json.dumps([str(get_db_path()), settings.get('active_broker_account_id'),
                              bool(settings.get('paper_trading', True))]).encode()).hexdigest()


@contextmanager
def _connection():
    from config import get_user_data_dir
    path = get_user_data_dir() / 'strategy_activation_reviews.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS reviews (scope TEXT, token TEXT, created_at TEXT, payload TEXT, PRIMARY KEY(scope, token))')
            yield conn
    finally:
        conn.close()


def dossier(matrix, settings, sid, ticker, version):
    from config.research_order_specs import execution_id
    from strategy_health.pair_recommendations import recommendations
    from trading.tested_strategy_research import strategy_details
    from strategy_health.exit_measurement import exit_measurement
    item = next((r for r in recommendations(matrix, settings)['recommendations']
                 if (r['strategy_id'], r['ticker'], r['strategy_version']) == (sid, ticker, version)), None)
    if not item or item['kind'] != 'new_match':
        raise ValueError('This recommendation changed. Refresh Settings before reviewing it.')
    strategy = next(s for s in matrix['strategies'] if execution_id(s['strategy_id'], s['version'], ticker) == sid and s['version'] == version)
    pair = next(p for p in strategy['pairs'] if p['ticker'] == ticker)
    source = strategy['strategy_id']
    library = strategy_details(source)
    rules = {'source': source, 'version': version, 'entry': None, 'exit': None, 'parameters': {}, 'source_sha256': None}
    if library and library.version == version:
        engine = library.factory()
        rules.update(timeframe_minutes=library.timeframe_minutes,
                     parameters=asdict(engine.config) if is_dataclass(getattr(engine, 'config', None)) else {},
                     source_sha256=sha256(Path(inspect.getfile(type(engine))).read_bytes()).hexdigest(),
                     exit=exit_measurement(source, library.exit_minutes)['authored_exit'])
        if source == 'V2_VWAP_PULLBACK':
            rules['entry'] = ('Completed 5-minute bars, from 9:45 AM Eastern. Calls: EMA8 above EMA20, '
                'VWAP rising across 5 bars, at least 4 of the preceding 5 trend bars above VWAP, '
                'prior low within 0.15% of prior VWAP, then close above VWAP. Puts mirror these conditions. '
                'Call stop is the lower of prior low and entry minus 1 ATR14; puts mirror. Target is 2R.')
            rules['exit'] = 'Original stop or 2R target checked on completed 5-minute bars; 75-bar hold cap and regular-session liquidation. These are existing research rules, not new exit proposals.'
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    native = REVIEWED_STRATEGIES.get(sid)
    if native and native.version == version:
        rules['registered_implementation'] = native.implementation
        rules['review_artifact'] = native.evidence_artifact
    from strategy_health.exit_protocols import PROTOCOLS
    rules['exit_protocol'] = PROTOCOLS.get(source)
    if pair.get('research_contract_profile'):
        from trading.research_contract_selection import research_contract_profile
        profile = research_contract_profile(source)
        rules['current_research_contract_profile'] = asdict(profile) if profile.version == pair['research_contract_profile'] else None
    rules['account_risk_fraction'] = settings.get('risk_per_trade')
    # Pin the exit dispatcher and source as well as the entry module.
    import strategy_health.exit_protocols as exit_source
    rules['exit_dispatch_sha256'] = sha256(Path(inspect.getfile(exit_source)).read_bytes()).hexdigest()
    if source == 'V2_VWAP_PULLBACK':
        from strategy_health import vwap_exit, impulse_exit
        rules['exit_sources'] = {m.__name__: sha256(Path(inspect.getfile(m)).read_bytes()).hexdigest()
                                 for m in (vwap_exit, impulse_exit)}
    coverage_keys = ('setups', 'option_results', 'option_result_days', 'quote_coverage_pct',
                     'mistimed_quotes_ignored', 'contract_selection_reasons', 'research_contract_profile')
    result = {'strategy_id': sid, 'ticker': ticker, 'version': version,
              'display_name': item['display_name'], 'account_mode': item['account_mode'],
              'can_enable': item['can_enable'], 'blocker': item['blocker'],
              'evidence': item['evidence'], 'rules': rules,
              'research_pair': {**pair, 'exit_comparison': pair.get('exit_comparison', []), 'contract_tests': pair.get('contract_tests', [])},
              'coverage': {k: pair.get(k) for k in coverage_keys},
              'sizing': 'Keep current account and strategy risk settings. This review cannot change risk limits.',
              'questions': ['Use the exact existing research rules, or request changes?',
                            'Approve implementation and execution testing, without activating trading?'],
              'test_requirement': 'Entry/exit parity, broker reconciliation, partial fills, duplicate orders, restart recovery and mandatory safety exits must pass before activation.',
              'tests': 'No new execution-test result is claimed by this approval workflow.',
              'execution_review_errors': list(reviewed_strategy_integrity_errors().get(sid, ())),
              'spec_version': 'guided-activation-v1'}
    result['token'] = sha256(json.dumps([_scope(settings), result], sort_keys=True, default=str).encode()).hexdigest()
    with _connection() as conn:
        row = conn.execute('SELECT payload FROM reviews WHERE scope=? AND token=?', (_scope(settings), result['token'])).fetchone()
        history = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM reviews WHERE scope=? ORDER BY created_at DESC LIMIT 100', (_scope(settings),))]
    result['approval'] = json.loads(row[0]) if row else None
    result['previous_approvals'] = [{'status': r['status'], 'created_at': r['created_at'], 'token': r['review']['token']}
        for r in history if (r['review']['strategy_id'], r['review']['ticker'], r['review']['version']) == (sid, ticker, version)
        and r['review']['token'] != result['token']]
    return result


def approve(review, settings, token, choice, notes, acknowledged, actor):
    if token != review['token']:
        raise ValueError('Evidence or rules changed. Reload and review before approving.')
    if not acknowledged or choice not in ('exact', 'changes'):
        raise ValueError('Choose the rules and confirm implementation-only approval.')
    notes = notes.strip()
    if choice == 'changes' and not notes:
        raise ValueError('Describe the changes you need.')
    if choice == 'exact' and notes:
        raise ValueError('Select Request changes to submit changed rules.')
    if len(notes) > 4000:
        raise ValueError('Keep requested changes under 4000 characters.')
    now = datetime.now(timezone.utc).isoformat()
    payload = {'status': 'changes_requested' if choice == 'changes' else 'implementation_approved',
               'created_at': now, 'actor': actor, 'choice': choice, 'notes': notes,
               'review': {k: v for k, v in review.items() if k not in ('approval', 'previous_approvals')},
               'trading_enabled_by_request': False}
    with _connection() as conn:
        conn.execute('INSERT OR IGNORE INTO reviews VALUES (?, ?, ?, ?)',
                     (_scope(settings), token, now, json.dumps(payload, default=str)))
        saved = json.loads(conn.execute('SELECT payload FROM reviews WHERE scope=? AND token=?', (_scope(settings), token)).fetchone()[0])
        if (saved['choice'], saved['notes']) != (choice, notes):
            raise ValueError('A different decision is already saved for this evidence. It has not been overwritten.')
    return saved
