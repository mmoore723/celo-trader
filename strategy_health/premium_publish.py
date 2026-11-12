"""Publish already-calculated premium evidence. No broker or policy writes."""
from strategy_health.exit_lab import publish
from strategy_health.premium_rules import clock
from zoneinfo import ZoneInfo


def publish_report(path, report):
    if not report.get('account'):
        return
    def metrics(m):
        return {**m,'net':m['net_pnl']}
    candidates=[]; chart=[]; trades=[]; missing=set()
    for c in report['candidates']:
        candidates.append(dict(id=c['rule'],name=c['label'],version=c['version'],
            baseline_metrics=metrics(c['baseline']),metrics=metrics(c['candidate']),
            improvement=c['mean_improvement'],interval=c['improvement_interval'],
            confidence=c['confidence'],tested_exits=c['tested_exits'],
            winners_to_losses=c['baseline_winners_to_losses'],pairs=c['paired_trades'],
            sessions=c['sessions'],coverage=c['coverage']*100,status=c['status']))
        missing.update(c['exclusions'])
        base=alternative=0
        for t in sorted(c['trades'],key=lambda t:(t['entry_at'],t['id'])):
            trades.append(dict(t,candidate_id=c['rule']))
            day=clock(t['entry_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
            if not t['prospective'] or not c['holdout_started_after'] or day<=c['holdout_started_after']:
                continue
            base+=t['baseline_net']; alternative+=t['candidate_net']
            chart.append(dict(candidate_id=c['rule'],pair_id=t['id'],time=t['entry_at'],
                              baseline=round(base,2),candidate=round(alternative,2)))
    first=report['candidates'][0]
    summary=dict(strategy=report['strategy_id'],name=report['strategy_id'],ticker=report['ticker'],
        version=report['strategy_version'],revision=report['specification']+':'+report['bucket'],
        status='complete' if report['evaluation_closed'] else 'collecting',
        recommendation='PROPOSE CHANGE' if any(c['promotion_ready'] for c in report['candidates']) else 'INSUFFICIENT EVIDENCE',
        result_kind='hypothetical shadow',baseline=report['baseline_source'],candidates=candidates,
        pairs=first['paired_trades'],sessions=first['sessions'],required_pairs=50,required_sessions=20,
        coverage=first['coverage']*100,last_collection=None,missing=sorted(missing),
        paper_policy=None,live_policy=None)
    # Raw stable identities remain in evidence; user-facing names use the same
    # canonical mapping as other pages.
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule=REVIEWED_STRATEGIES.get(report['strategy_id'])
    if rule: summary['name']=rule.display_name
    detail=dict(rules={'baseline':report.get('exact_baseline') or report['baseline_source']},
        candidates=[dict(c['rule_specification'],rule=c['rule'],confidence=c['confidence'],tested_exits=c['tested_exits']) for c in report['candidates']],
        history=[],exclusions=[dict(rule=c['rule'],reasons=c['exclusions']) for c in report['candidates']],
        evidence=[dict(rule=c['rule'],selection=c['selection'],gates=c['gates']) for c in report['candidates']],chart=chart)
    publish(path,report['account'],report['mode'],summary,detail,trades)
