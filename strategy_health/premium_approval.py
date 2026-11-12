"""Persisted evidence approval. Browser metrics never confer order authority."""
import json
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from strategy_health.premium_rules import VERSION, RULES, EXECUTION_RULES
from trading.premium_policy import scope, fingerprint


def execution_certified():
    root=Path(__file__).resolve().parents[1]
    path=root/'config'/'premium_execution_certification.json'
    if not path.exists():
        return False
    try:
        proof=json.loads(path.read_text())
        return (proof['version']==VERSION and proof['passed'] is True
                and all(sha256((root/name).read_bytes()).hexdigest()==digest
                        for name,digest in proof['sources'].items())
                and len(proof['sources'])>=4)
    except (ValueError,KeyError,OSError,TypeError):
        return False


def approve(conn, settings, bucket, rule, report_hash):
    if settings.get('paper_trading') is not True:
        raise ValueError('Only paper policy approval is supported. Live settings are unchanged.')
    if rule not in RULES:
        raise ValueError('Unknown profit-taking rule')
    if rule not in EXECUTION_RULES:
        raise ValueError('This additional exit is research-only and cannot be activated')
    row=conn.execute('SELECT payload FROM premium_exit_reports WHERE bucket=?',(bucket,)).fetchone()
    if row is None:
        raise ValueError('No saved evaluation for this bucket')
    report=json.loads(row[0]); account=settings.get('active_broker_account_id')
    if report['mode']!='paper' or not account or report['account']!=account:
        raise ValueError('Account or mode mismatch')
    if report['fingerprint']!=report_hash or report['specification']!=VERSION:
        raise ValueError('Evaluation changed. Review the updated results.')
    candidate=next(c for c in report['candidates'] if c['rule']==rule)
    if not report.get('evaluation_closed') or not candidate.get('evidence_passed') or not all(candidate.get('gates',{}).values()):
        raise ValueError('Insufficient paired evidence. No policy changed.')
    from strategy_health.premium_native import baseline_spec
    expected=baseline_spec(settings,report['strategy_id'],report['ticker'],report['strategy_version'])
    if report.get('exact_baseline')!=expected:
        raise ValueError('The exact current exit policy has not been verified for these trades')
    from strategy_health.premium_research import assess
    from zoneinfo import ZoneInfo
    from strategy_health.premium_rules import clock
    cutoff=candidate.get('holdout_started_after')
    if not cutoff or not candidate.get('selection_complete'):
        raise ValueError('A separate newer-trade holdout is required')
    selection=[]; holdout=[]
    for r in candidate.get('trades',[]):
        if not r.get('prospective'): continue
        day=clock(r['entry_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        (holdout if day>cutoff else selection).append(r)
    count=len(report['candidates'])
    if count!=len(RULES) or {c['rule'] for c in report['candidates']}!=set(RULES):
        raise ValueError('The complete frozen candidate family is required')
    verified=assess(holdout,candidate.get('attempted',0),tested_exits=count)
    initial=assess(selection,candidate.get('selection_attempted',0),tested_exits=count)
    if not verified['evidence_passed'] or not initial['evidence_passed']:
        raise ValueError('Saved trade-level evidence does not satisfy approval criteria')
    if not execution_certified():
        raise ValueError('Execution regression certification is missing or stale')
    from config.research_order_specs import execution_id
    from config.strategy_catalog import REVIEWED_STRATEGIES
    sid=execution_id(report['strategy_id'],report['strategy_version'],report['ticker'])
    route=REVIEWED_STRATEGIES.get(sid)
    if route is None:
        raise ValueError('Exact execution route is unavailable')
    now=datetime.now(timezone.utc).isoformat()
    cursor=conn.execute('INSERT INTO premium_exit_decisions(at,account,action,bucket,rule,report_hash) VALUES (?,?,?,?,?,?)',
        (now,account,'paper_approval',bucket,rule,report_hash))
    policy=dict(version=VERSION,rule=rule,account=account,mode='paper',strategy=sid,
        ticker=report['ticker'],strategy_version=route.version,approval_id=cursor.lastrowid,
        approved_at=now,evidence_fingerprint=report_hash,baseline='entry-frozen native policy')
    policy['fingerprint']=fingerprint(policy)
    assignments=dict(settings.get('premium_exit_paper_assignments') or {})
    key=scope(account,sid,report['ticker'],route.version)
    previous=assignments.get(key)
    assignments[key]=policy
    return {'premium_exit_paper_assignments':assignments},dict(policy=policy,previous=previous)
