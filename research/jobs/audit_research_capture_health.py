"""Read-only capture audit. Counts are attempts, never profitability evidence."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone


def audit(user, full_inventory=False):
    from auth.context import set_current_user
    set_current_user(user, user, False)
    from config import get_settings, get_db_path
    settings = get_settings()
    conn = sqlite3.connect('file:' + str(get_db_path()) + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    account = settings.get('active_broker_account_id') or ''
    result = {'captured_at_utc':datetime.now(timezone.utc).isoformat(), 'user':user,
              'mode':'paper' if settings.get('paper_trading',True) else 'live',
              'broker_account_id':account, 'tickers':[]}
    selected = set(settings.get('research_tickers', []))
    inventory = set(selected)
    if full_inventory:
        inventory.update(r[0] for r in conn.execute('SELECT DISTINCT ticker FROM shadow_candidates'))
    result.update(inventory_scope='historical_and_selected' if full_inventory else 'selected',
                  historical_ticker_count=conn.execute('SELECT count(DISTINCT ticker) FROM shadow_candidates').fetchone()[0])
    try:
        for ticker in sorted(inventory):
            rows = [dict(r) for r in conn.execute('''SELECT strategy_id,
                json_extract(metadata_json,'$.strategy_version') AS version,
                count(*) AS attempts,min(observed_at) AS first_seen,max(observed_at) AS last_seen
                FROM shadow_candidates WHERE ticker=? AND coalesce(broker_account_id,'')=?
                GROUP BY strategy_id,version''',(ticker,account))]
            missing_entries = [dict(r) for r in conn.execute('''SELECT s.strategy_id,
                json_extract(s.metadata_json,'$.strategy_version') AS version,
                coalesce(json_extract(s.metadata_json,'$.manual_plan.contract_preview.reason'),'not_recorded') AS reason,
                count(*) AS affected_attempts,min(s.observed_at) AS first_seen,max(s.observed_at) AS last_seen
                FROM shadow_candidates s WHERE ticker=? AND coalesce(s.broker_account_id,'')=?
                AND NOT EXISTS (SELECT 1 FROM candidate_option_quote_observations q
                    WHERE q.candidate_id=s.candidate_id AND q.observation_kind='entry' AND q.ask>0)
                GROUP BY s.strategy_id,version,reason''',(ticker,account))]
            exits = [dict(r) for r in conn.execute('''SELECT s.strategy_id,
                json_extract(s.metadata_json,'$.strategy_version') AS version,e.protocol,e.status,e.reason,
                count(*) AS affected_attempts,min(s.observed_at) AS first_seen,max(s.observed_at) AS last_seen,
                max(e.detected_at) AS last_detection
                FROM research_strategy_exits e JOIN shadow_candidates s USING(candidate_id)
                WHERE s.ticker=? AND coalesce(s.broker_account_id,'')=?
                GROUP BY s.strategy_id,version,e.protocol,e.status,e.reason''',(ticker,account))]
            result['tickers'].append({'ticker':ticker,'currently_selected':ticker in selected,
                                      'buckets':rows,'entry_failures':missing_entries,
                                      'authored_exit_status':exits})
    finally:
        conn.close()
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--user',required=True)
    parser.add_argument('--full-inventory',action='store_true')
    args=parser.parse_args()
    print(json.dumps(audit(args.user,args.full_inventory),indent=2))
