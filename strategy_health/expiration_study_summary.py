"""Descriptive, exact-cohort comparison; never supplies promotion evidence."""
from collections import Counter
import json
from statistics import median

from strategy_health.expiration_study_exits import PROTOCOL_BY_STRATEGY, normalized_profit
from strategy_health.pair_recommendations import summarize, timestamp
from trading.expiration_study_selection import PROFILE


def independent(rows):
    """Keep all raw plays elsewhere; this view removes overlapping exposure."""
    selected, end = [], None
    for row in sorted(rows, key=lambda r: (timestamp(r['entry_at']), r['id'])):
        if end is None or timestamp(row['entry_at']) >= end:
            selected.append(row)
            end = timestamp(row['exit_at'])
    return selected


def metrics(rows):
    values = [r['pnl'] for r in rows]
    batches = Counter()
    for row in rows:
        batches[timestamp(row['exit_at'])] += row['pnl']
    peak = equity = drawdown = 0
    for _, profit in sorted(batches.items()):
        equity += profit
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
    return {**summarize(rows),
            'net_one_contract_pnl': round(sum(values), 2) if values else None,
            'average_one_contract_pnl': round(sum(values)/len(values), 2) if values else None,
            'maximum_drawdown_one_contract': round(drawdown, 2) if values else None}


def comparison(pairs):
    changes = [row['longer']['pnl']-row['primary']['pnl'] for row in pairs]
    return dict(results=len(pairs), primary=metrics([row['primary'] for row in pairs]),
                longer=metrics([row['longer'] for row in pairs]),
                improved=sum(v > .000001 for v in changes), worsened=sum(v < -.000001 for v in changes),
                unchanged=sum(abs(v) <= .000001 for v in changes),
                average_change=round(sum(changes)/len(changes), 2) if changes else None,
                median_change=round(median(changes), 2) if changes else None)


def summary(samples, studies, strategy_id, primary_results):
    """Caller passes distinct timely current-rule candidates for one ticker.

    Only candidate-matched completed exits may establish a paired difference.
    A missing primary exit with a selected contract is NOT longer-only coverage.
    """
    enrolled, rejected = [], 0
    for sample in samples:
        row = studies.get(sample['candidate_id'])
        if row is None:
            continue
        state = row['state']
        meta = json.loads(sample['metadata_json']) if isinstance(sample['metadata_json'], str) else sample['metadata_json']
        if (state.get('profile_version') != PROFILE or state.get('strategy_id') != strategy_id
                or state.get('protocol') != PROTOCOL_BY_STRATEGY.get(strategy_id)
                or state.get('strategy_version') != meta.get('strategy_version')
                or row['ticker'] != sample['ticker']):
            rejected += 1
            continue
        enrolled.append((sample, row))
    if not enrolled and not rejected:
        return None
    primary = {r['id']: r for r in primary_results}
    results, pairs, longer_only, incomplete_primary = [], [], [], []
    for sample, row in enrolled:
        state = row['state']
        pnl = normalized_profit(state)
        if pnl is None:
            continue
        result = dict(id=sample['candidate_id'], entry_at=state['entry_quote_at'],
                      exit_at=state['bid_at'], pnl=pnl)
        results.append(result)
        if result['id'] in primary:
            original = primary[result['id']]
            pairs.append(dict(id=result['id'], primary=original, longer=result,
                              entry_at=min((original['entry_at'], result['entry_at']), key=timestamp),
                              exit_at=max((original['exit_at'], result['exit_at']), key=timestamp)))
        elif not sample['entry_contract']:
            longer_only.append(result)
        else:
            incomplete_primary.append(result)
    reasons = Counter(row['selection'].get('reason') or 'selected' for _, row in enrolled)
    return dict(profile_version=PROFILE, recommendation_eligible=False, setups=len(enrolled),
                rejected_identity=rejected, selection_reasons=dict(reasons),
                statuses=dict(Counter(row['state']['status'] for _, row in enrolled)),
                selected_contracts=sum(bool(row['state'].get('contract_symbol')) for _, row in enrolled),
                completed=metrics(results), non_overlapping=metrics(independent(results)),
                matched=comparison(pairs), matched_non_overlapping=comparison(independent(pairs)),
                longer_only=metrics(longer_only), longer_only_non_overlapping=metrics(independent(longer_only)),
                primary_incomplete=len(incomplete_primary),
                first_setup_at=min((s['observed_at'] for s, _ in enrolled), default=None),
                last_setup_at=max((s['observed_at'] for s, _ in enrolled), default=None))
