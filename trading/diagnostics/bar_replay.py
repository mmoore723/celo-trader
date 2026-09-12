"""Reproduce captured native bar decisions in isolated function namespaces.

Never patch a live module, replace live dedupe state, call a broker or route
orders. Minute-boundary clock brackets are explicitly not verified.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import sqlite3
from types import FunctionType

import pandas as pd

from trading.diagnostics.bar_evidence import PROTOCOL, SPECS, MAX_HISTORY_ROWS, FRAME_CHUNK_ROWS, scoped_state, source_hashes
from trading.diagnostics.orb_evidence import canonical, MAX_ROWS
from trading.diagnostics.orb_replay import unpack_record
from strategies.market_structure import Side
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars

REPLAY_OWNER = 'isolated-native-replay'


def restore_state(namespace, state):
    for name, value in state.items():
        if value['kind'] == 'dict':
            container = {}
            for key, item in value['entries']:
                if name == '_active_breakout_by_session':
                    item = (Side(item[0]), item[1])
                container[(REPLAY_OWNER, *key)] = deepcopy(item)
        elif value['kind'] == 'set':
            container = {(REPLAY_OWNER, *key) for key in value['entries']}
        else:
            raise ValueError('Unsupported state container')
        namespace[name] = container


def isolated_evaluate(record, frame):
    spec = SPECS[record['strategy_id']]
    module = importlib.import_module(spec[0])
    namespace = vars(module).copy()
    # Clone only trusted local code, never execute source from the payload.
    # Every module-local helper shares the new namespace and isolated caches.
    for name, value in vars(module).items():
        if isinstance(value, FunctionType) and value.__module__ == module.__name__:
            clone = FunctionType(value.__code__, namespace, value.__name__, value.__defaults__, value.__closure__)
            clone.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = clone
    restore_state(namespace, record['state_before'])
    now = record['evaluated_at']
    # Trend has no public `now` parameter. Its trusted completed-bar helper
    # gets the captured cutoff through the cloned globals, not a module patch.
    namespace['_complete_five_minute_bars'] = lambda frame, now=None: _complete_five_minute_bars(
        frame, now=record['evaluated_at'] if now is None else now)
    kwargs = dict(ticker=record['ticker'], execution_scope=REPLAY_OWNER)
    if record['strategy_id'] != 'V2_SPY_TREND_CONT':
        kwargs['now'] = now
    signal, error = None, None
    try:
        signal = namespace[spec[1]](frame, **kwargs)
    except Exception as exc:
        error = type(exc).__name__
    return dict(signal=asdict(signal) if signal else None, error=error,
                state_after=scoped_state(namespace, spec[3], REPLAY_OWNER, record['ticker']))


def read_frame_rows(inputs, read_blob):
    """Restore exact row order under a fixed budget; never trim or fill data.

    Legacy inline inputs remain readable in their recorded source environment.
    This does not bypass verify_record's source/pandas identity checks.
    """
    if 'data' in inputs:
        if 'data_chunks' in inputs or not isinstance(inputs['data'], list) or len(inputs['data']) > MAX_ROWS:
            raise ValueError('Invalid inline frame or mixed formats')
        return inputs['data']
    refs = inputs.get('data_chunks')
    count = inputs.get('row_count')
    if (not isinstance(refs, list) or len(refs) > (MAX_ROWS + FRAME_CHUNK_ROWS - 1) // FRAME_CHUNK_ROWS
            or type(count) is not int or not 0 <= count <= MAX_ROWS):
        raise ValueError('Frame reference budget')
    rows = []
    for ref in refs:
        chunk = unpack_record(read_blob(ref), ref)
        if not isinstance(chunk, list) or not 0 < len(chunk) <= FRAME_CHUNK_ROWS or len(rows)+len(chunk) > MAX_ROWS:
            raise ValueError('Frame row budget')
        rows.extend(chunk)
    if len(rows) != count:
        raise ValueError('Frame row count mismatch')
    return rows


def verify_record(packed, digest, read_blob):
    record = unpack_record(packed, digest)
    spec = SPECS.get(record['strategy_id'])
    if (record['protocol'] != PROTOCOL or not spec or record['ticker'] not in spec[2]
            or record['scope'] != 'enabled_native_execution'):
        raise ValueError('Wrong native evaluator scope')
    if record['sources'] != source_hashes() or record['pandas_version'] != pd.__version__:
        raise ValueError('Source or pandas version mismatch')
    start, end = record['evaluated_at'], record['finished_at']
    if start.tzinfo is None or end.tzinfo is None or end < start or start.floor('min') != end.floor('min'):
        raise ValueError('Ambiguous evaluator clock bracket; not verified')
    if set(record['state_before']) != set(spec[3]) or set(record['state_after']) != set(spec[3]):
        raise ValueError('Missing or unexpected state')
    inputs = unpack_record(read_blob(record['input_digest']), record['input_digest'])
    if len(inputs['history']) > (MAX_HISTORY_ROWS + 127) // 128:
        raise ValueError('History reference budget')
    frame = pd.DataFrame(read_frame_rows(inputs, read_blob), columns=inputs['columns'])
    for column, dtype in zip(inputs['columns'], inputs['dtypes'], strict=True):
        frame[column] = frame[column].astype(dtype)
    history = []
    for ref in inputs['history']:
        rows = unpack_record(read_blob(ref), ref)
        if len(rows) > 128 or len(history) + len(rows) > MAX_HISTORY_ROWS:
            raise ValueError('History row budget')
        history.extend(tuple(row) for row in rows)
    if history:
        frame.attrs['multi_session_bars'] = tuple(history)
    actual = isolated_evaluate(record, frame)
    if canonical(actual) != canonical({key: record[key] for key in actual}):
        raise ValueError('Recorded transition does not reproduce')
    return record


def report(database, *, account_digest, paper):
    if not account_digest or not isinstance(paper, bool):
        raise ValueError('Explicit account and mode required')
    conn = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)
    conn.execute('PRAGMA query_only=ON')
    counts = {}
    def read_blob(ref):
        row = conn.execute('SELECT payload FROM input_blobs WHERE digest=?', (ref,)).fetchone()
        if row is None:
            raise ValueError('Missing input blob')
        return row[0]
    try:
        for packed, digest in conn.execute('SELECT payload,payload_sha256 FROM bar_evaluations WHERE account_digest=? AND paper=? ORDER BY id',
                                           (account_digest, int(paper))):
            record = verify_record(packed, digest, read_blob)
            if record['account_digest'] != account_digest or record['paper'] != paper:
                raise ValueError('Payload/index scope mismatch')
            key = record['strategy_id'] + ':' + record['ticker']
            item = counts.setdefault(key, dict(evaluations=0, signals=0, errors=0))
            item['evaluations'] += 1
            item['signals'] += record['signal'] is not None
            item['errors'] += record['error'] is not None
    finally:
        conn.close()
    if not counts:
        raise ValueError('No matching evidence; not verified')
    return dict(pairs=counts, continuous_capture_proven=False, option_fills_verified=False,
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
