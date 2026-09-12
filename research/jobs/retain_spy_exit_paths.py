"""Retain only selected SPY contract paths from existing compressed archives.

Read-only source files, no downloads or extraction directory. Checkpoint after
each source date, validate source hashes against the corrected-clock baseline.
The output contains quote data only, no credentials/account or order authority.
"""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import zstandard


def moment(text):
    value = datetime.fromisoformat(text.replace('Z','+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timezone required')
    return value


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def checkpoint(path, data):
    fd, name = tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    with os.fdopen(fd,'w') as output:
        json.dump(data,output,indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(name,path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','archive','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args = p.parse_args()
    baseline = json.loads(args.baseline.read_text())
    if (baseline['protocol'] != 'spy_trend_cbbo_interval_end_30m_research_v1'
            or not baseline['complete'] or len(baseline['rows'])!=baseline['candidates']
            or str(args.archive.resolve())!=baseline['archive']):
        raise ValueError('Invalid baseline/archive identity')
    by_day = defaultdict(list)
    for entry in baseline['rows']:
        if entry['status'] not in ('priced','missing_exit'):
            raise ValueError('Unexpected baseline status; do not drop candidates silently')
        by_day[entry['date']].append(entry)
    identity = dict(protocol='retained_spy_cbbo_paths_v1',baseline_sha256=digest(args.baseline),
                    code_sha256=digest(Path(__file__)))
    result = json.loads(args.output.read_text()) if args.output.exists() else dict(
        **identity,processed_dates=[],rows=[],complete=False)
    if any(result.get(k)!=v for k,v in identity.items()):
        raise ValueError('Checkpoint identity differs')
    days = sorted(by_day)
    if result['processed_dates']!=days[:len(result['processed_dates'])]:
        raise ValueError('Invalid checkpoint order')
    expected = [r['candidate_id'] for day in result['processed_dates'] for r in by_day[day]]
    if [r['candidate_id'] for r in result['rows']]!=expected:
        raise ValueError('Checkpoint rows differ')
    for day in days[len(result['processed_dates']):]:
        if shutil.disk_usage(args.output.parent).free<2*1024**3:
            raise ValueError('Disk reserve below 2 GiB')
        datetime.strptime(day,'%Y-%m-%d')
        member = args.archive/f'opra-pillar-{day.replace("-", "")}.cbbo-1m.csv.zst'
        if digest(member)!=baseline['member_sha256'][day]:
            raise ValueError('Source archive member changed')
        wanted = defaultdict(list)
        selected = {r['candidate_id']:[] for r in by_day[day]}
        for entry in by_day[day]:
            wanted[entry['contract']].append(entry)
        with member.open('rb') as raw,zstandard.ZstdDecompressor().stream_reader(raw) as decoder:
            with io.TextIOWrapper(decoder,encoding='utf-8',newline='') as text:
                reader = csv.DictReader(text)
                required = {'symbol','rtype','ts_recv','bid_px_00','ask_px_00','bid_sz_00','ask_sz_00'}
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError('Missing quote provenance')
                for q in reader:
                    symbol = q['symbol'].strip()
                    if symbol not in wanted:
                        continue
                    if q['rtype']!='193':
                        raise ValueError('Expected CBBO-1m')
                    now = moment(q['ts_recv'])
                    if now.second or now.microsecond:
                        raise ValueError('Expected minute-end availability clock')
                    for entry in wanted[symbol]:
                        start = moment(entry['entry_time'])
                        if start <= now <= start+timedelta(minutes=31):
                            selected[entry['candidate_id']].append(dict(contract=symbol,time=now.isoformat(),
                                bid=q['bid_px_00'],ask=q['ask_px_00'],bid_size=q['bid_sz_00'],ask_size=q['ask_sz_00']))
        for entry in by_day[day]:
            result['rows'].append(dict(candidate_id=entry['candidate_id'],date=day,
                contract=entry['contract'],entry_time=entry['entry_time'],snapshots=selected[entry['candidate_id']]))
        result['processed_dates'].append(day)
        result['complete'] = len(result['processed_dates'])==len(days)
        checkpoint(args.output,result)
        print(f'{len(result["processed_dates"])}/{len(days)} days; {len(result["rows"])}/{baseline["candidates"]} entries retained',flush=True)


if __name__=='__main__':
    main()
