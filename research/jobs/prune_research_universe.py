"""Explicit, transactional research deletion. Never deletes broker/trade evidence."""
import argparse
import json
import sqlite3

CHILDREN = (
    'candidate_option_quote_observations', 'candidate_contract_alternatives',
    'learning_ranker_scores', 'learning_examples', 'research_strategy_exits',
    'research_strategy_exit_variants', 'research_premium_exit_paths',
    'research_option_profit_tests', 'research_reference_contract_tests',
    'research_expiration_comparisons',
)
TICKER_TABLES = ('paper_research_option_observations', 'scanner_candle_observations',
                 'research_bar_recoveries')


def prune(conn, keep, *, apply=False):
    if not keep or any(not isinstance(x, str) or not x.isupper() for x in keep):
        raise ValueError('An explicit nonempty uppercase keep list is required')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA secure_delete=ON')
    conn.execute('BEGIN IMMEDIATE')
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        marks = ','.join('?' for _ in keep)
        conn.execute('CREATE TEMP TABLE removed_candidates(candidate_id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO removed_candidates SELECT candidate_id FROM shadow_candidates '
                     'WHERE ticker NOT IN ('+marks+')', keep)
        ids = 'SELECT candidate_id FROM removed_candidates'
        for table in ('trades', 'broker_order_events'):
            if table in tables and conn.execute(f'SELECT 1 FROM "{table}" WHERE candidate_id IN ({ids}) LIMIT 1').fetchone():
                raise ValueError('Excluded research has broker evidence; refusing deletion')
        cols = {r[1] for r in conn.execute('PRAGMA table_info(shadow_candidates)')}
        if 'linked_trade_id' in cols and conn.execute(f'SELECT 1 FROM shadow_candidates WHERE candidate_id IN ({ids}) AND linked_trade_id IS NOT NULL LIMIT 1').fetchone():
            raise ValueError('Excluded research is linked to a trade')
        before_fk = set(conn.execute('PRAGMA foreign_key_check').fetchall())
        result = {'keep': sorted(keep), 'removed_tickers': [r[0] for r in conn.execute(
            f'SELECT DISTINCT ticker FROM shadow_candidates WHERE candidate_id IN ({ids}) ORDER BY ticker')],
                  'deleted_rows': {}, 'applied': apply}
        def remove(table, predicate, params=()):
            if table in tables:
                result['deleted_rows'][table] = conn.execute(f'DELETE FROM "{table}" WHERE {predicate}', params).rowcount
        if 'learning_examples' in tables:
            remove('learning_practice_sessions', f'example_id IN (SELECT example_id FROM learning_examples WHERE candidate_id IN ({ids}))')
        for table in CHILDREN:
            remove(table, f'candidate_id IN ({ids})')
        remove('shadow_candidates', f'candidate_id IN ({ids})')
        for table in TICKER_TABLES:
            remove(table, 'ticker NOT IN ('+marks+')', keep)
        if set(conn.execute('PRAGMA foreign_key_check').fetchall()) - before_fk:
            raise ValueError('Cleanup introduced broken references')
        conn.execute('DROP TABLE removed_candidates')
        conn.commit() if apply else conn.rollback()
        return result
    except BaseException:
        conn.rollback()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--keep', required=True, help='Exact comma-separated keep list')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with sqlite3.connect('file:'+args.database+'?mode=rw', uri=True, timeout=5) as conn:
        print(json.dumps(prune(conn, args.keep.split(','), apply=args.apply), indent=2))
