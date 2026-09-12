"""Frozen exit comparisons for enabled Failed-Range Recovery and Afternoon FVG.

Uses original reviewed contracts, not the affordable alternatives. Preserve
entry times, original stop levels, 30-minute cap and $3.30 roundtrip cost.
Run both previously declared exit policies without selecting new parameters.
No broker calls, data downloads, production routing or settings changes.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from research.engine.data import load_csv
from research.jobs.replay_spy_structure_exit import evaluate_pair
from research.jobs.replay_two_leg_initial_loss import compare
from research.jobs.structure_exit_candidate import ExitState, MarketContext
from research.jobs.structure_alignment_candidate import AlignmentExitState

SOURCES = {
    'V2_FAILED_OR_BREAK_VWAP_REVERSION': 'failed_range',
    'V2_SPY_AFTERNOON_FVG': 'fvg',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt_entry(sid, row):
    if sid not in SOURCES or row['profile'] != 'reviewed_bounds' or row['status'] != 'priced':
        raise ValueError('Wrong strategy, profile or unpriced source')
    if sid == 'V2_FAILED_OR_BREAK_VWAP_REVERSION':
        if not row['native'] or row['independent'] != row['native_independent']:
            raise ValueError('Not the unchanged native entry cohort')
        return {**row, 'signal_meta': {'v2_stop': row['stop']}}
    if 'v2_stop' not in row['signal_meta']:
        raise ValueError('Original thesis stop absent')
    return {**row, 'signal_meta': dict(row['signal_meta'])}


def source_entries(sid, baseline, retained):
    rows = [row for row in baseline['rows'] if row['profile'] == 'reviewed_bounds'
            and (sid != 'V2_FAILED_OR_BREAK_VWAP_REVERSION' or row['native'])]
    paths = {row['id']: row for row in retained['rows'] if row['strategy_id'] == sid}
    if len(paths) != len(rows) or set(paths) != {sid+'|'+r['candidate_id'] for r in rows}:
        raise ValueError('Retained cohort differs')
    result = []
    for row in rows:
        path = paths[sid+'|'+row['candidate_id']]
        if path['independent'] != row['independent']:
            raise ValueError('Independence flag changed')
        result.append((adapt_entry(sid, row), {'snapshots': path['control_path']}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baselines', 'retained', 'bars', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output exists; preserve earlier evidence')
    retained = json.loads(args.retained.read_text())
    if not retained['complete'] or retained['protocol'] != 'spy_three_strategies_affordability_fixed142_v1':
        raise ValueError('Wrong or unfinished retained source')
    bars = load_csv(args.bars)
    market = MarketContext(bars.bars)
    results, input_hashes = {}, {str(args.retained): digest(args.retained), str(args.bars): bars.sha256}
    for sid, prefix in SOURCES.items():
        file = args.baselines/(prefix+'_corrected_clock_baseline_2026-09-11.json')
        manifest_file = args.baselines/(prefix+'_current_signal_manifest_2026-09-11.json')
        baseline, manifest = json.loads(file.read_text()), json.loads(manifest_file.read_text())
        if (not baseline['complete'] or baseline['quote_clock_policy'] != 'cbbo_interval_end_ts_recv_v2'
                or digest(file) != retained['baseline_sha256'][sid]
                or digest(manifest_file) != baseline['manifest_sha256']
                or manifest['bars_sha256'] != bars.sha256):
            raise ValueError('Changed baseline, manifest or underlying bars')
        input_hashes.update({str(file): digest(file), str(manifest_file): digest(manifest_file)})
        entries = source_entries(sid, baseline, retained)
        results[sid] = {}
        for name, policy in [('structure_retest_v1', ExitState), ('structure_retest_alignment_v2', AlignmentExitState)]:
            rows = []
            for entry, path in entries:
                row = evaluate_pair(entry, path, market, state_type=policy)
                rows.append(row)
            results[sid][name] = dict(rows=rows, all_activity=compare(rows),
                independent=compare([r for r in rows if r['independent']]),
                exit_reasons=dict(Counter(r['variant']['reason'] for r in rows)))
            print(sid, name, json.dumps({k:v for k,v in results[sid][name].items() if k != 'rows'}), flush=True)
    files = [Path(__file__), *(Path(__file__).with_name(name+'.py') for name in (
        'replay_spy_structure_exit', 'replay_two_leg_initial_loss', 'structure_exit_candidate',
        'structure_alignment_candidate'))]
    result = dict(protocol='other_enabled_spy_original_contract_structure_exit_v1', complete=True,
        input_sha256=input_hashes, code_sha256={str(p):digest(p) for p in files}, results=results,
        limitations=['Historical development comparison, not untouched holdout validation',
                     'Original contracts remain subject to current account affordability rejection',
                     'Unpaired cases are explicitly excluded from paired metrics, not counted as holds',
                     'Drawdown in comparison is closed-trade cumulative, not full-account intratrade drawdown',
                     'No contract-policy changes or deployment approval'])
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(result, out, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
