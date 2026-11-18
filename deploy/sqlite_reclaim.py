"""Offline sparse reclamation of SQLite freelist LEAF pages only.

SQLite file format: freelist leaf pages contain no database information. Trunk
pages contain allocation metadata and MUST remain allocated and unchanged.
https://www.sqlite.org/fileformat.html#the_freelist

Manual maintenance, never an automatic deploy step. Requires stopped writers,
a verified external full backup, rollback journal mode and an exclusive SQLite
lock. Does not delete rows, compact live pages or change the logical file size.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess


def leaf_ranges(path):
    """Validate every freelist pointer before returning aligned byte ranges."""
    with Path(path).open('rb') as stream:
        header=stream.read(100)
        if header[:16]!=b'SQLite format 3\0':raise ValueError('not_sqlite')
        size=struct.unpack('>H',header[16:18])[0]
        size=65536 if size==1 else size
        if size<512 or size>65536 or size&(size-1):raise ValueError('invalid_page_size')
        if header[18:20]!=b'\x01\x01':raise ValueError('requires_offline_rollback_journal_mode')
        total=Path(path).stat().st_size//size
        if Path(path).stat().st_size%size:raise ValueError('partial_page')
        trunk,count=struct.unpack('>II',header[32:40])
        seen=set();leaves=[];trunks=[]
        def accept(page):
            if page<=1 or page>total or page in seen:raise ValueError('invalid_or_duplicate_free_page')
            seen.add(page)
        while trunk:
            accept(trunk);trunks.append(trunk)
            stream.seek((trunk-1)*size);data=stream.read(size)
            next_trunk,n=struct.unpack('>II',data[:8])
            if n>(size-header[20])//4-2:raise ValueError('invalid_leaf_count')
            for offset in range(n):
                page=struct.unpack('>I',data[8+4*offset:12+4*offset])[0]
                accept(page);leaves.append(page)
            trunk=next_trunk
        if len(seen)!=count:raise ValueError('freelist_count_mismatch')
        ranges=[]
        for page in sorted(leaves):
            offset=(page-1)*size
            if ranges and ranges[-1][0]+ranges[-1][1]==offset:
                ranges[-1][1]+=size
            else:ranges.append([offset,size])
        return dict(page_size=size,leaf_pages=len(leaves),trunk_pages=len(trunks),ranges=ranges)


def active_hash(path,ranges):
    """Hash every byte except proven unused leaf pages, including all indexes."""
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        cursor=0
        for offset,length in ranges+[[Path(path).stat().st_size,0]]:
            stream.seek(cursor)
            remaining=offset-cursor
            while remaining:
                block=stream.read(min(4*1024*1024,remaining))
                if not block:raise ValueError('unexpected_eof')
                digest.update(block);remaining-=len(block)
            cursor=offset+length
    return digest.hexdigest()


def reclaim(path, *, apply=False, backup_sha256=None):
    path=Path(path).absolute()
    if path.is_symlink() or not path.is_file():raise ValueError('unsafe_database_path')
    if any(Path(str(path)+suffix).exists() and Path(str(path)+suffix).stat().st_size for suffix in ('-wal','-journal')):
        raise ValueError('uncheckpointed_or_active_journal')
    db=sqlite3.connect('file:'+str(path)+'?mode=rw',uri=True,timeout=1)
    try:
        if db.execute('PRAGMA journal_mode').fetchone()[0]!='delete':raise ValueError('requires_offline_rollback_journal_mode')
        db.execute('BEGIN EXCLUSIVE')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('pre_integrity_failed')
        plan=leaf_ranges(path)
        before=path.stat().st_blocks*512
        result=dict(leaf_pages=plan['leaf_pages'],trunk_pages=plan['trunk_pages'],eligible_bytes=sum(n for _,n in plan['ranges']),allocated_before=before,applied=False)
        if not apply:return result
        if not backup_sha256 or len(backup_sha256)!=64:raise ValueError('verified_external_backup_sha256_required')
        full=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(4*1024*1024),b''):full.update(block)
        if full.hexdigest()!=backup_sha256:raise ValueError('database_changed_since_backup')
        protected=active_hash(path,plan['ranges'])
        for offset,length in plan['ranges']:
            subprocess.run(['fallocate','--punch-hole','--keep-size','--offset',str(offset),'--length',str(length),str(path)],check=True)
        with path.open('rb') as stream:os.fsync(stream.fileno())
        if active_hash(path,plan['ranges'])!=protected:raise RuntimeError('PROTECTED_BYTES_CHANGED_RESTORE_BACKUP')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise RuntimeError('POST_INTEGRITY_FAILED_RESTORE_BACKUP')
        result.update(applied=True,protected_sha256=protected,allocated_after=path.stat().st_blocks*512,recovered_bytes=before-path.stat().st_blocks*512)
        return result
    finally:
        db.rollback();db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('database',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup-sha256')
    args=parser.parse_args()
    print(json.dumps(reclaim(args.database,apply=args.apply,backup_sha256=args.backup_sha256)),flush=True)
