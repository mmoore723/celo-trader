"""Remove only obsolete hashed frontend JS/CSS; preserve evidence and rollback assets."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

REF = re.compile(r'[A-Za-z0-9_.-]+\.(?:js(?:\.map)?|css(?:\.map)?|woff2?|ttf|svg|png|webp)')
HASHED = re.compile(r'-[A-Za-z0-9_-]{8,}\.(?:js|css)(?:\.map)?$')


def cleanup(repo, *, dry_run=True, grace_seconds=86400):
    repo = Path(repo).resolve()
    assets = repo/'frontend/dist/assets'
    if assets.is_symlink() or not assets.is_dir():
        raise ValueError('unsafe_assets_directory')
    files = {p.name:p for p in assets.iterdir() if p.is_file() and not p.is_symlink()}
    roots = [(repo/'frontend/dist/index.html').read_text()]
    for i in range(5):
        roots.append(subprocess.check_output(['git','show',f'HEAD~{i}:frontend/dist/index.html'],cwd=repo,text=True))
    pending = []
    for html in roots:
        for name in re.findall(r'/assets/([^\s"\'<>]+)', html):
            if name not in files:
                raise ValueError('missing_protected_asset:'+name)
            pending.append(name)
    used = set()
    while pending:
        name = pending.pop()
        if name in used:
            continue
        used.add(name)
        if name.endswith(('.js','.css')):
            pending.extend(n for n in REF.findall(files[name].read_text()) if n in files and n not in used)
        if name+'.map' in files:
            pending.append(name+'.map')
    cutoff = time.time()-grace_seconds
    targets = [p for n,p in files.items() if n not in used and HASHED.search(n) and p.stat().st_mtime < cutoff]
    result = dict(dry_run=dry_run, protected_files=len(used), grace_hours=grace_seconds/3600,
                  removed_files=len(targets), removed_bytes=sum(p.stat().st_size for p in targets))
    for path in targets:
        if not dry_run:
            path.unlink()
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=Path('.'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(cleanup(args.repo,dry_run=not args.apply)))
