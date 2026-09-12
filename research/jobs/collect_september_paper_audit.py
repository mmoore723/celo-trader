"""Save the user-approved scoped SSH export without exposing its rows to stdout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

DEST = Path('/Users/melanin/Claude/Projects/Stock/audit_data/september_paper_audit.json')
SOURCE = Path(__file__).with_name('export_september_paper_audit.py')

def main():
    DEST.parent.mkdir(mode=0o700, exist_ok=True)
    if DEST.parent.is_symlink():
        raise RuntimeError('Refusing symlink destination directory')
    fd = os.open(DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as destination, SOURCE.open('rb') as source:
        try:
            result = subprocess.run([
                'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
                '-i', '/Users/melanin/.ssh/celo_trader.pem',
                'ec2-user@3.148.153.141', 'python3 -'],
                stdin=source, stdout=destination, stderr=subprocess.PIPE,
                timeout=50, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Export timed out; partial local file retained, no rows printed') from None
    if result.returncode:
        # Do not print remote stderr, which is not guaranteed to be data-free.
        raise RuntimeError(f'Export failed with exit {result.returncode}; local file retained, no rows printed')
    raw = DEST.read_bytes()
    payload = json.loads(raw)
    assert payload['scope']['account_anchor_trade'] == 222
    assert payload['scope']['start'] == '2026-09-08'
    assert payload['scope']['end_exclusive'] == '2026-09-12'
    print(json.dumps({'saved': str(DEST), 'bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest(),
                      'counts': {key: len(payload[key]) for key in
                                 ('trades', 'candidates', 'option_quotes', 'broker_events')}}))

if __name__ == '__main__':
    main()
