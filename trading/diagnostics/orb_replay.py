"""Read-only replay of native ORB evidence, not inferred historical entries.

This verifies each recorded transition. It cannot prove uninterrupted capture,
continuous market quotes, order placement, option fills or profitability.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

import pandas as pd

from trading.diagnostics.orb_evidence import (
    PROTOCOL, MAX_PAYLOAD_BYTES, canonical, decode, source_hashes,
)
from trading.orb_retouch_execution import update_one_minute_orb_retouch


def unpack_record(packed, expected_hash):
    inflater = zlib.decompressobj()
    raw = inflater.decompress(packed, MAX_PAYLOAD_BYTES + 1)
    if len(raw) > MAX_PAYLOAD_BYTES or not inflater.eof or inflater.unused_data:
        raise ValueError('Invalid or oversized evidence payload')
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('Evidence hash mismatch')
    return decode(json.loads(raw))


def verify_record(packed, expected_hash):
    record = unpack_record(packed, expected_hash)
    if record['protocol'] != PROTOCOL or record['scope'] != 'enabled_native_execution' or record['ticker'] != 'TSLA':
        raise ValueError('Not native enabled TSLA ORB evidence')
    if record['sources'] != source_hashes() or record['pandas_version'] != pd.__version__:
        raise ValueError('Evaluator source or pandas version differs; use recorded environment')
    state = deepcopy(record['state_before'])
    frame = pd.DataFrame(record['frame']['data'], columns=record['frame']['columns'])
    result, status, error = None, 'evaluation_error', None
    try:
        result, status = update_one_minute_orb_retouch(state, frame, ticker='TSLA',
                    quote_price=record['quote_price'], now=record['evaluated_at'].to_pydatetime())
    except Exception as exc:
        error = type(exc).__name__
    actual = dict(state_after=state, signal=asdict(result) if result else None, status=status, error=error)
    if canonical(actual) != canonical({key: record[key] for key in actual}):
        raise ValueError('Recorded evaluation does not reproduce')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--account-digest', required=True)
    parser.add_argument('--mode', choices=['paper', 'live'], required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    count = signals = errors = 0
    try:
        for packed, digest in conn.execute('SELECT payload,payload_sha256 FROM evaluations WHERE account_digest=? AND paper=? ORDER BY id',
                (args.account_digest, int(args.mode == 'paper'))):
            record = verify_record(packed, digest)
            if record['account_digest'] != args.account_digest or record['paper'] != (args.mode == 'paper'):
                raise ValueError('Payload identity differs from scoped index')
            count += 1
            signals += record['signal'] is not None
            errors += record['error'] is not None
    finally:
        conn.close()
    if not count:
        raise ValueError('No matching evidence; not verified')
    print(json.dumps(dict(verified_evaluations=count, emitted_signals=signals, reproduced_errors=errors,
                         continuous_capture_proven=False, option_fills_verified=False)))


if __name__ == '__main__':
    main()
