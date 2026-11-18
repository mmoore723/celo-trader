"""Lossless versioned storage for option observations. Keys and times never change.

Plain JSON remains readable. Compression is storage only, never a price repair.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zlib

MAGIC = b'CELOQUOTE1\0'
MAX_BYTES = 4 * 1024 * 1024


def decode_text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes) or not value.startswith(MAGIC):
        raise ValueError('unknown_quote_storage_format')
    digest, compressed = value[len(MAGIC):len(MAGIC)+32], value[len(MAGIC)+32:]
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError('invalid_quote_compression_length')
        if hashlib.sha256(raw).digest() != digest:
            raise ValueError('quote_storage_checksum_mismatch')
        return raw.decode('utf-8')
    except (zlib.error, UnicodeDecodeError) as exc:
        raise ValueError('corrupt_compressed_quote') from exc


def encode_text(value):
    raw = value.encode('utf-8')
    if len(raw) > MAX_BYTES:
        return value
    packed = MAGIC + hashlib.sha256(raw).digest() + zlib.compress(raw, 6)
    if len(packed) >= len(raw):
        return value
    if decode_text(packed) != value:
        raise ValueError('quote_roundtrip_failed')
    return packed


def migrate_batch(db, batch=500):
    """Atomic checkpoint and bounded writes. Roll back whole batch on corruption.

    No VACUUM: requires no second database copy. Freed pages stay reusable.
    """
    db.execute('CREATE TABLE IF NOT EXISTS quote_compression_progress (id INTEGER PRIMARY KEY CHECK(id=1), cursor INTEGER NOT NULL)')
    db.commit()
    with db:
        row = db.execute('SELECT cursor FROM quote_compression_progress WHERE id=1').fetchone()
        cursor = row[0] if row else 0
        rows = db.execute('SELECT rowid,payload FROM observations WHERE rowid>? ORDER BY rowid LIMIT ?', (cursor,batch)).fetchall()
        saved = changed = 0
        for rowid, value in rows:
            original = decode_text(value)
            packed = encode_text(original)
            if isinstance(value, str) and isinstance(packed, bytes):
                db.execute('UPDATE observations SET payload=? WHERE rowid=?', (packed,rowid))
                persisted = db.execute('SELECT payload FROM observations WHERE rowid=?', (rowid,)).fetchone()[0]
                if decode_text(persisted) != original:
                    raise ValueError('persisted_quote_roundtrip_failed')
                saved += len(original.encode()) - len(packed)
                changed += 1
        if rows:
            cursor = rows[-1][0]
            db.execute('INSERT OR REPLACE INTO quote_compression_progress VALUES(1,?)', (cursor,))
    return dict(scanned=len(rows), compressed=changed, payload_bytes_saved=saved, cursor=cursor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    # rw deliberately refuses to create a missing evidence database.
    db = sqlite3.connect('file:' + str(args.database.resolve()) + '?mode=rw', uri=True, timeout=.5)
    db.execute('PRAGMA wal_autocheckpoint=256')
    totals = dict(scanned=0, compressed=0, payload_bytes_saved=0)
    end = time.monotonic()+args.seconds
    while time.monotonic()<end:
        try:
            result = migrate_batch(db)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc):
                raise
            time.sleep(.2)
            continue
        for key in totals:
            totals[key] += result[key]
        if result['scanned'] == 0:
            break
        time.sleep(.02)
    db.execute('PRAGMA wal_checkpoint(PASSIVE)')
    totals['reusable_database_bytes'] = db.execute('PRAGMA freelist_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
    db.close()
    print(json.dumps(totals))


if __name__ == '__main__':
    main()
