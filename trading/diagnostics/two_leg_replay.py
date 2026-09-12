"""Read-only exact native Two-Leg transition replay, not fill verification."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

import pandas as pd

from trading.diagnostics.orb_evidence import canonical
from trading.diagnostics.orb_replay import unpack_record
from trading.diagnostics.two_leg_evidence import PROTOCOL, STRATEGY_ID, source_hashes
from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback


def verify_record(packed, expected_hash):
    record = unpack_record(packed, expected_hash)
    if (record['protocol'] != PROTOCOL or record['strategy_id'] != STRATEGY_ID
            or record['scope'] != 'enabled_native_execution' or record['ticker'] != 'TSLA'):
        raise ValueError('Not enabled native TSLA Two-Leg evidence')
    if record['sources'] != source_hashes() or record['pandas_version'] != pd.__version__:
        raise ValueError('Evaluator source or pandas version differs; use recorded environment')
    state = deepcopy(record['state_before'])
    frame = pd.DataFrame(record['frame']['data'], columns=record['frame']['columns'])
    signal, status, error = None, 'evaluation_error', None
    try:
        signal, status = update_two_leg_trend_pullback(
            state, frame, ticker='TSLA', now=record['evaluated_at'].to_pydatetime())
    except Exception as exc:
        error = type(exc).__name__
    actual = dict(state_after=state, signal=asdict(signal) if signal else None, status=status, error=error)
    if canonical(actual) != canonical({key: record[key] for key in actual}):
        raise ValueError('Recorded evaluation does not reproduce')
    return record


def report(database, *, account_digest, paper):
    if not isinstance(paper, bool) or not account_digest:
        raise ValueError('Explicit account and mode required')
    conn = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    count = signals = errors = 0
    try:
        for packed, digest in conn.execute(
                'SELECT payload,payload_sha256 FROM two_leg_evaluations WHERE account_digest=? AND paper=? ORDER BY id',
                (account_digest, int(paper))):
            record = verify_record(packed, digest)
            if record['account_digest'] != account_digest or record['paper'] != paper:
                raise ValueError('Payload identity differs from scoped index')
            count += 1
            signals += record['signal'] is not None
            errors += record['error'] is not None
    finally:
        conn.close()
    if not count:
        raise ValueError('No matching evidence; not verified')
    return dict(verified_evaluations=count, emitted_signals=signals, reproduced_errors=errors,
                continuous_capture_proven=False, option_fills_verified=False,
                whole_account_replay_complete=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--account-digest', required=True)
    parser.add_argument('--mode', choices=['paper', 'live'], required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.database, account_digest=args.account_digest, paper=args.mode == 'paper')))


if __name__ == '__main__':
    main()
