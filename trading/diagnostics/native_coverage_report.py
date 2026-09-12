"""Read-only summary of recorded native decisions, not a coverage certificate."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

from trading.diagnostics.native_coverage import MAX_PAYLOAD_BYTES, PROTOCOL


def read_record(packed, digest, account_digest, paper):
    inflater = zlib.decompressobj()
    raw = inflater.decompress(packed, MAX_PAYLOAD_BYTES + 1)
    if len(raw)>MAX_PAYLOAD_BYTES or not inflater.eof or inflater.unused_data:
        raise ValueError('Invalid compressed coverage record')
    if hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError('Coverage hash mismatch')
    record = json.loads(raw)
    if (record['protocol']!=PROTOCOL or record['account_digest']!=account_digest or
            not isinstance(record['paper'],bool) or record['paper']!=paper):
        raise ValueError('Coverage scope mismatch')
    return record


def summarize(path, account_digest, paper):
    conn = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    count = errors = 0
    by_pair = {}
    first = last = None
    try:
        conn.execute('PRAGMA query_only=ON')
        for packed, digest in conn.execute('SELECT payload,payload_sha256 FROM coverage WHERE account_digest=? AND paper=? ORDER BY id',
                                           (account_digest,int(paper))):
            record = read_record(packed,digest,account_digest,paper)
            count += 1
            errors += bool(record.get('error'))
            at = record['evaluated_at']
            first, last = min(first or at,at), max(last or at,at)
            for sid, details in record['strategies'].items():
                key = sid+'|'+record['ticker']
                pair = by_pair.setdefault(key,dict(passes=0,evaluation=Counter(),routing=Counter(),errors=0))
                pair['passes'] += 1
                pair['evaluation'][details['evaluation']] += 1
                pair['routing'][details['routing']] += 1
                pair['errors'] += bool(record.get('error')) or any(
                    e['status'] in {'evaluation_error','post_evaluation_error'} for e in details['events'])
    finally:
        conn.close()
    return dict(recorded_passes=count, router_errors=errors, first_recorded_at=first,
                last_recorded_at=last, by_pair=by_pair, full_session_coverage=False,
                complete_replay_inputs=False, option_fills_verified=False,
                caveat='No signal returned can include duplicate suppression. Unrecorded passes are unknown, not no setup.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('--account-digest',required=True)
    parser.add_argument('--mode',choices=['paper','live'],required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.database,args.account_digest,args.mode=='paper'),indent=2))


if __name__=='__main__':
    main()
