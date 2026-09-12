"""Read-only replay inventory for six enabled strategies and seven native pairs.

This checks recorded evaluator transitions, not session completeness, routing,
option fills or profitability. No broker calls, orders or database creation.
CLI exit 2 means missing or failed pair evidence; exit 0 means only that all
seven pairs have clean replayed records, not that trading is validated.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
import zlib

from trading.diagnostics.native_coverage import PAIRS
from trading.diagnostics import orb_replay, two_leg_replay, bar_replay
from trading.diagnostics.orb_replay import unpack_record

TABLES = {
    'evaluations': ('V2_ORB_PULLBACK', orb_replay.verify_record),
    'two_leg_evaluations': ('V2_TSLA_TWO_LEG_TREND_PULLBACK', two_leg_replay.verify_record),
    'bar_evaluations': (None, bar_replay.verify_record),
}


def inventory(database, *, account_digest, paper):
    if not account_digest or not isinstance(paper, bool):
        raise ValueError('Explicit account and mode required')
    pairs = {sid + ':' + ticker: dict(records=0, replayed=0, signals=0,
                                    reproduced_errors=0, failures=Counter())
             for sid, tickers in PAIRS.items() for ticker in tickers}
    report = dict(database_exists=False, pairs=pairs, unassigned_failures=Counter(),
                  tables_missing=[], all_pairs_have_replayed_records=False,
                  continuous_capture_proven=False, option_fills_verified=False,
                  whole_account_replay_complete=False)
    path = Path(database)
    if not path.exists():
        report['tables_missing'] = list(TABLES)
        return finish(report)
    report['database_exists'] = True
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        def read_blob(ref):
            if 'input_blobs' not in names:
                raise ValueError('Missing input blob table')
            row = conn.execute('SELECT payload FROM input_blobs WHERE digest=?', (ref,)).fetchone()
            if row is None:
                raise ValueError('Missing input blob')
            return row[0]

        for table, (fixed_sid, verify) in TABLES.items():
            if table not in names:
                report['tables_missing'].append(table)
                continue
            # Identifiers come exclusively from the fixed local TABLES mapping.
            for packed, digest in conn.execute(
                    f'SELECT payload,payload_sha256 FROM {table} WHERE account_digest=? AND paper=? ORDER BY id',
                    (account_digest, int(paper))):
                item = None
                try:
                    record = unpack_record(packed, digest)
                    if record['account_digest'] != account_digest or record['paper'] is not paper:
                        raise ValueError('Payload/index scope mismatch')
                    sid = fixed_sid or record['strategy_id']
                    if fixed_sid and record.get('strategy_id', fixed_sid) != fixed_sid:
                        raise ValueError('Wrong strategy table')
                    key = sid + ':' + record['ticker']
                    if key not in pairs or (table == 'bar_evaluations' and sid not in bar_replay.SPECS):
                        raise ValueError('Wrong native pair')
                    item = pairs[key]
                    item['records'] += 1
                    verified = verify(packed, digest, read_blob) if table == 'bar_evaluations' else verify(packed, digest)
                    item['replayed'] += 1
                    item['signals'] += verified['signal'] is not None
                    item['reproduced_errors'] += verified['error'] is not None
                except (ValueError, KeyError, TypeError, sqlite3.Error, zlib.error) as exc:
                    # Fixed codes only: do not echo private payload values.
                    failures = report['unassigned_failures'] if item is None else item['failures']
                    failures[failure_code(exc)] += 1
    finally:
        conn.close()
    return finish(report)


def failure_code(exc):
    if isinstance(exc, zlib.error):
        return 'invalid_compressed_record'
    message = str(exc).lower()
    for phrase, code in (
            ('source or pandas', 'recorded_environment_required'),
            ('ambiguous evaluator clock', 'ambiguous_clock'),
            ('does not reproduce', 'transition_mismatch'),
            ('hash mismatch', 'checksum_mismatch'),
            ('missing input blob', 'missing_input_blob'),
            ('scope mismatch', 'account_or_mode_mismatch'),
            ('wrong strategy table', 'strategy_table_mismatch'),
            ('wrong native pair', 'native_pair_mismatch')):
        if phrase in message:
            return code
    return type(exc).__name__


def finish(report):
    for item in report['pairs'].values():
        item['status'] = ('replay_failed' if item['failures'] else
                          'evaluator_error_reproduced' if item['reproduced_errors'] else
                          'recorded_decisions_replayed' if item['replayed'] else 'no_records')
    report['all_pairs_have_replayed_records'] = (
        not report['unassigned_failures'] and
        all(p['replayed'] > 0 and not p['failures'] and not p['reproduced_errors']
            for p in report['pairs'].values()))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--account-digest', required=True)
    parser.add_argument('--mode', choices=['paper', 'live'], required=True)
    args = parser.parse_args(argv)
    result = inventory(args.database, account_digest=args.account_digest, paper=args.mode == 'paper')
    print(json.dumps(result, indent=2))
    return 0 if result['all_pairs_have_replayed_records'] else 2


if __name__ == '__main__':
    sys.exit(main())
