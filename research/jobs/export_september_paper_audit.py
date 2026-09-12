"""Approved, read-only, admin-account Sep 8–11 audit; JSON to stdout only.

Run with production Python over SSH stdin. No app imports, migrations, writes,
credentials, other users or raw broker payloads. Anchor account to visible trade222.
"""
import json
import sqlite3
from datetime import datetime, timezone

DB = '/opt/celo_trader/user_data/admin/trades_paper.db'
START, END = '2026-09-08', '2026-09-12'
STRATEGIES = ('V2_SPY_TREND_CONT', 'V2_TSLA_TWO_LEG_TREND_PULLBACK',
              'V2_ORB_PULLBACK', 'V2_SPY_AFTERNOON_FVG',
              'V2_FAILED_OR_BREAK_VWAP_REVERSION', 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG')
META_KEYS = {
    'strategy_version', 'strategy_fingerprint', 'entry_timing',
    'validated_entry_rule', 'directional_confirmation', 'reference_945',
    'vwap', 'fast_ema', 'slow_ema', 'atr', 'impulse_extreme',
    'pullback_low', 'pullback_high', 'reclaim_level', 'v2_entry_reference',
    'v2_stop', 'v2_target', 'v2_hypothesis', 'option_contract_profile',
    'contract_profile', 'research_contract_profile', 'source',
}

def selected_meta(value):
    try:
        data = json.loads(value or '{}')
    except (ValueError, TypeError):
        return {'invalid_json': True}
    if not isinstance(data, dict):
        return {'invalid_object': True}
    return {key: value for key, value in data.items()
            if key in META_KEYS and isinstance(value, (str, int, float, bool, type(None)))}

def export():
    conn = sqlite3.connect('file:' + DB + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    anchor = conn.execute('SELECT broker_account_id,strategy_id,paper,entry_time FROM trades WHERE id=222').fetchone()
    assert anchor and anchor['strategy_id'] == STRATEGIES[0] and anchor['paper'] == 1
    assert anchor['entry_time'].startswith('2026-09-11') and anchor['broker_account_id']
    account = anchor['broker_account_id']
    trades = [dict(row) for row in conn.execute('''SELECT id,parent_trade_id,
      ticker,strategy_id,status,paper,contract_symbol,option_type,strike,expiry,
      contracts,entry_price,exit_price,entry_time,exit_time,entry_fill_time,
      exit_fill_time,realized_pnl,exit_reason,candidate_id,strategy_context_json,
      entry_order_id,exit_order_id FROM trades
      WHERE broker_account_id=? AND paper=1 AND strategy_id IN (?,?,?,?,?,?)
      AND substr(entry_time,1,10)>=? AND substr(entry_time,1,10)<? ORDER BY id''',
      (account, *STRATEGIES, START, END))]
    output = {'exported_at': datetime.now(timezone.utc).isoformat(),
              'scope': {'account_anchor_trade':222, 'mode':'paper', 'start':START,
                        'end_exclusive':END, 'strategies':STRATEGIES},
              'trades':trades, 'candidates':[], 'option_quotes':[], 'broker_events':[]}
    seen = set()
    for trade in trades:
        trade['strategy_context'] = selected_meta(trade.pop('strategy_context_json'))
        candidate = trade['candidate_id']
        if candidate and candidate not in seen:
            seen.add(candidate)
            row = conn.execute('''SELECT candidate_id,observed_at,ticker,strategy_id,
              direction,trigger_bar,metadata_json,final_outcome,linked_trade_id
              FROM shadow_candidates WHERE candidate_id=? AND broker_account_id=?
              AND strategy_id=? AND ticker=?''',
              (candidate, account, trade['strategy_id'], trade['ticker'])).fetchone()
            if row:
                row = dict(row)
                row['metadata'] = selected_meta(row.pop('metadata_json'))
                output['candidates'].append(row)
        output['option_quotes'].extend(dict(row) for row in conn.execute('''
          SELECT trade_id,observed_at,observation_kind,contract_symbol,bid,ask,
          fill_price,source FROM option_quote_observations WHERE trade_id=?
          AND substr(observed_at,1,10)>=? AND substr(observed_at,1,10)<?
          ORDER BY observed_at,id''', (trade['id'], START, END)))
        output['broker_events'].extend(dict(row) for row in conn.execute('''
          SELECT id,event_time,broker,order_id,event_type,status,contract_symbol,
          strategy_id,side,requested_qty,filled_qty,limit_price,fill_price,
          linked_trade_id FROM broker_order_events WHERE broker_account_id=?
          AND paper=1 AND (linked_trade_id=? OR order_id IN (?,?))
          AND substr(event_time,1,10)>=? AND substr(event_time,1,10)<? ORDER BY id''',
          (account, trade['id'], trade['entry_order_id'], trade['exit_order_id'], START, END)))
    conn.rollback()
    conn.close()
    print(json.dumps(output, separators=(',', ':'), allow_nan=False))

if __name__ == '__main__':
    export()
