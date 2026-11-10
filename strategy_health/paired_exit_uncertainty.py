"""Read-only paired evidence statistics, never a qualification or promotion gate.

No default experiment settings. Caller must obtain approval and freeze inputs
before prospective use. Session bootstrap assumes independent session clusters;
it cannot cure selection bias, missing outcomes or nonstationary markets.
"""
from decimal import Decimal
from math import ceil, isfinite
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from strategy_health.paired_exit_accounting import clock, money, summarize


def _session(row):
    return clock(row['entry_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()


def _describe(rows):
    valid = [r for r in rows if r['status'] == 'evaluable']
    values = [money(r['improvement']) for r in valid]
    report = summarize(rows)[0] if rows else None
    return dict(attempts=len(rows), paired_trades=len(valid),
        enrolled_sessions=len({_session(r) for r in rows}),
        paired_sessions=len({_session(r) for r in valid}),
        coverage=len(valid)/len(rows) if rows else None,
        mean_improvement=sum(values, Decimal(0))/len(values) if values else None,
        median_improvement=median(values) if values else None,
        baseline=report['baseline'] if report else None,
        candidate=report['candidate'] if report else None,
        baseline_winners_turned_losses=sum(r['baseline_winner_to_loss'] for r in valid))


def analyze_bucket(attempts, *, confidence, family_size, resamples, seed, holdout_fraction):
    """One scope/policy/cost-model bucket. Dates are split before exclusions.

    Each bootstrap draw samples sessions with replacement, retaining all their
    valid paired trades; the statistic is total improvement / total trade count,
    not an unweighted mean of session averages. Resampling is memory-bounded.
    """
    if (isinstance(confidence, bool) or not isfinite(confidence) or not 0 < confidence < 1
            or isinstance(holdout_fraction, bool) or not isfinite(holdout_fraction)
            or not 0 < holdout_fraction < 1):
        raise ValueError('invalid_confidence_or_holdout_fraction')
    for name, value in (('family_size', family_size), ('resamples', resamples)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError('positive_integer_' + name + '_required')
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError('nonnegative_integer_seed_required')
    rows = list(attempts)
    reports = summarize(rows)
    if len(reports) != 1:
        raise ValueError('exactly_one_bucket_and_cost_model_required')
    for row in rows:
        session = _session(row)
        if row['status'] not in ('evaluable', 'blocked'):
            raise ValueError('unknown_attempt_status')
        if row['status'] == 'evaluable':
            if row['session'] != session:
                raise ValueError('entry_session_mismatch')
            expected = money(row['candidate']['net']) - money(row['baseline']['net'])
            if money(row['improvement']) != expected:
                raise ValueError('paired_improvement_does_not_reconcile')
    sessions = sorted({_session(r) for r in rows})
    cut = len(sessions) - ceil(len(sessions)*holdout_fraction)
    development_days = set(sessions[:cut])
    holdout_days = set(sessions[cut:])
    development = [r for r in rows if _session(r) in development_days]
    holdout = [r for r in rows if _session(r) in holdout_days]
    report = dict(scope=reports[0]['scope'], pricing_identity=reports[0]['pricing_identity'],
        baseline_policy=reports[0]['baseline_policy'], candidate_policy=reports[0]['candidate_policy'],
        all=_describe(rows), development=_describe(development), holdout=_describe(holdout),
        development_sessions=sorted(development_days), holdout_sessions=sorted(holdout_days),
        uncertainty=None, recommendation='INSUFFICIENT EVIDENCE',
        qualification='not performed; approved frozen criteria, fixed calendar end and execution gates required',
        settings=dict(confidence=confidence,family_size=family_size,resamples=resamples,
                      seed=seed,holdout_fraction=holdout_fraction),
        assumptions=['Session clusters treated as independent; serial dependence can invalidate bounds.',
                     'Missing outcomes are not imputed; exclusions can bias the paired sample.',
                     'Family size must include all frozen hypotheses, including abandoned variants.',
                     'Percentile bootstrap bounds are approximate, not a profitability guarantee.'])
    valid = [r for r in rows if r['status'] == 'evaluable']
    cluster_days = sorted({_session(r) for r in valid})
    if len(cluster_days) < 2:
        report['uncertainty_status'] = 'insufficient_paired_sessions'
        return report
    sums = np.array([float(sum((money(r['improvement']) for r in valid if _session(r)==day),Decimal(0)))
                     for day in cluster_days], dtype=float)
    counts = np.array([sum(_session(r)==day for r in valid) for day in cluster_days], dtype=float)
    if not np.isfinite(sums).all():
        raise ValueError('bootstrap_numeric_overflow')
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    batch_size = max(1, min(256, 1000000 // len(cluster_days)))
    for start in range(0,resamples,batch_size):
        end=min(start+batch_size,resamples)
        indices=rng.integers(0,len(cluster_days),size=(end-start,len(cluster_days)))
        means[start:end]=sums[indices].sum(axis=1)/counts[indices].sum(axis=1)
    alpha=(1-confidence)/family_size
    report['uncertainty'] = dict(method='paired_session_cluster_percentile_bootstrap',
        adjusted_one_sided_lower_bound=float(np.quantile(means,alpha)),
        two_sided_interval=[float(np.quantile(means,alpha/2)),float(np.quantile(means,1-alpha/2))],
        adjusted_tail_probability=alpha, paired_sessions=len(cluster_days),
        expected_resamples_in_lower_tail=resamples*alpha)
    report['uncertainty_status'] = 'computed_not_qualification'
    if resamples*alpha < 20:
        report['assumptions'].append('Adjusted tail has fewer than 20 expected resamples; numerical tail resolution is weak.')
    report['holdout_mean_positive'] = (report['holdout']['mean_improvement'] > 0
                                      if report['holdout']['mean_improvement'] is not None else None)
    return report
