"""Read-only journal review exercises. Never manufacture executed trades."""
import json
import math
from collections import Counter


def parsed(value):
    try:
        data = json.loads(value or '{}')
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def exercises(rows, version, mode):
    result, excluded = [], Counter()
    partial_roots = {r['parent_trade_id'] for r in rows if r.get('parent_trade_id')}
    for row in rows:
        versions = {str(v) for v in (parsed(row.get('strategy_context_json')).get('strategy_version'),
                                    parsed(row.get('metadata_json')).get('strategy_version')) if v}
        if versions != {version}:
            excluded['Missing, conflicting or different version'] += 1
            continue
        if row.get('parent_trade_id') or row['id'] in partial_roots:
            excluded['Partial-position review not supported yet'] += 1
            continue
        try:
            pnl = float(row['realized_pnl'])
            entry, exit_price = float(row['entry_price']), float(row['exit_price'])
            if not all(math.isfinite(v) for v in (pnl, entry, exit_price)) or not row.get('exit_time'):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            excluded['Incomplete recorded result'] += 1
            continue
        confirmed = all(row.get(k) for k in ('entry_order_id','exit_order_id','entry_fill_time','exit_fill_time'))
        result.append(dict(id=f"trade-{row['id']}", source=f"{mode.title()} trade journal" + (' with recorded broker fill references' if confirmed else ' (fill confirmation incomplete)'),
            title=f"{row['ticker']} {row['option_type']} • {row['entry_time']}",
            question='Did this recorded trade finish with a profit, a loss, or break even?',
            facts=f"Entry premium ${entry:.2f}; exit premium ${exit_price:.2f}; {row['contracts']} contracts. Recorded realized P&L: ${pnl:.2f}.",
            choices=['Profit','Loss','Break even'], answer='Profit' if pnl > 0 else 'Loss' if pnl < 0 else 'Break even',
            explanation=f"Recorded exit reason: {row.get('exit_reason') or 'Not captured'}. Entry reason: {row.get('entry_reason') or 'Not captured'}. This reviews the recorded outcome, not whether the entry was correct. P&L uses the journal value; fee completeness is not independently verified.",
            synthetic=False))
    return result[:20], dict(excluded)


def library(strategy_id, ticker, version):
    from config import get_settings
    from database.connection import _conn_for_mode
    from api.routes.learning_guide import guide
    reference = guide(strategy_id, ticker, version)
    settings = get_settings()
    account = settings.get('active_broker_account_id')
    mode = 'paper' if settings.get('paper_trading', True) else 'live'
    rows = []
    if account:
        with _conn_for_mode(mode) as conn:
            rows = [dict(r) for r in conn.execute('''
                SELECT t.*, s.metadata_json FROM trades t LEFT JOIN shadow_candidates s
                ON s.candidate_id=t.candidate_id AND s.broker_account_id=t.broker_account_id
                AND s.strategy_id=t.strategy_id AND s.ticker=t.ticker
                WHERE t.broker_account_id=? AND t.paper=? AND t.strategy_id=? AND t.ticker=?
                ORDER BY t.entry_time DESC LIMIT 500
            ''',(account, int(mode == 'paper'), strategy_id, ticker.upper())).fetchall()]
    # Open legs participate in partial-position detection but are never exercises.
    partial_roots = {r['parent_trade_id'] for r in rows if r.get('parent_trade_id')}
    closed = [r for r in rows if r['status'] == 'closed' and r['id'] not in partial_roots]
    actual, excluded = exercises(closed, version, mode)
    if not account:
        excluded['Active broker account not identified'] = 1
    condition = reference['steps'][0] if reference['steps'] else 'The strategy entry checklist must be confirmed.'
    samples = [dict(id='sample-wait', source='Illustrative teaching example, not a real trade',
        title='Example 1: a condition is missing', facts=f'Required rule: {condition} In this fictional example, that condition is not confirmed.',
        question='Should you treat this as a confirmed setup?', choices=['Yes','No'], answer='No',
        explanation='A missing required condition is not confirmation. This example does not create a signal or change the strategy.', synthetic=True),
        dict(id='sample-outcome', source='Illustrative teaching example, not a real trade',
        title='Example 2: review an outcome', facts='A fictional long option costs $2.00 and is sold for $1.80. One contract represents 100 shares. Fees are excluded.',
        question='What is the gross result?', choices=['$20 profit','$20 loss','$2 loss'], answer='$20 loss',
        explanation='($1.80 - $2.00) × 100 = -$20. A loss alone does not prove the entry violated its rules.', synthetic=True)]
    return dict(actual=actual, samples=samples, exclusions=excluded, mode=mode,
                source='Account-scoped journal; latest 500 rows inspected; at most 20 exercises', order_authority=False)
