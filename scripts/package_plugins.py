#!/usr/bin/env python3
"""Stage exact-git-tree offline Zinit sources. No unpinned plugin download."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def git(*args, cwd=None, output=True):
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1'}
    p=subprocess.run(['git',*args],cwd=cwd,env=env,capture_output=True,check=True)
    return p.stdout.decode().strip() if output else None

def verify_lock(lock):
    assert lock['schema']==1 and len(lock['plugins'])>=5
    names=[]
    for entry in lock['plugins']:
        name,repo,sha,tree=(entry[x] for x in ('name','repo','commit','tree'))
        if not name.replace('-','').isalnum() or '/' not in repo or len(sha)!=40 or len(tree)!=40:
            raise ValueError('invalid pin')
        int(sha,16);int(tree,16);names.append(name)
    if len(names)!=len(set(names)):raise ValueError('duplicate pinned plugin')

def extract_plugin_archive(raw: bytes, dst: Path, name: str) -> int:
    """Stage a pinned Git archive without creating filesystem links.

    Upstream documentation may use relative links to files inside the *same*
    archive. Verify the complete member inventory first, then materialize
    those links as ordinary files. Hard links, external/dangling links, linked
    directories and linked-link chains remain forbidden.
    """
    import posixpath
    from pathlib import PurePosixPath

    if dst.is_symlink() or not dst.is_dir():
        raise ValueError(f'{name}: unsafe output directory')
    entries = {}
    ordinary = {}
    links = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for member in archive:
            path = member.name.removesuffix('/')
            if (not path or path.startswith('/') or '\\' in path
                    or any(part in ('..', '.') for part in path.split('/'))
                    or not all(path.split('/')) or path in entries):
                raise ValueError(f'{name}: unsafe archive entry {member.name!r}')
            if not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError(f'{name}: unsupported archive entry {member.name!r}')
            if member.isfile():
                if member.size > 2_000_000:
                    raise ValueError(f'{name}: oversized plugin file')
                ordinary[path] = archive.extractfile(member).read()
            if member.issym():
                link = member.linkname
                if not link or link.startswith('/') or '\\' in link:
                    raise ValueError(f'{name}: unsafe archive link {path!r}')
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), link))
                if (resolved in ('.', '..') or resolved.startswith('../')
                        or resolved.startswith('/') or not resolved):
                    raise ValueError(f'{name}: external archive link {path!r}')
                links[path] = resolved
            entries[path] = member

    # Reject file-vs-directory collisions before touching the destination.
    for path in entries:
        parent = PurePosixPath(path).parent
        while str(parent) != '.':
            item = entries.get(str(parent))
            if item is not None and not item.isdir():
                raise ValueError(f'{name}: conflicting archive members')
            parent = parent.parent

    # The link target must be a verified *ordinary* regular member, not a
    # directory, another symlink, or a path outside the pinned Git archive.
    for path, target in links.items():
        if target not in ordinary:
            raise ValueError(f'{name}: unsafe archive link target {path!r}')

    # A package run always supplies a fresh staging tree. Reject preexisting
    # symlinks even if they would resolve inside the destination.
    for path, member in entries.items():
        dest = dst / path
        if (dest.is_symlink() or
            not dest.resolve().is_relative_to(dst.resolve())):
            raise ValueError(f'{name}: unsafe staging path {path!r}')
        if member.isdir():
            if dest.exists() and not dest.is_dir():
                raise ValueError(f'{name}: staging path conflicts with a file')
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if any(part.is_symlink() for part in (dest, *dest.parents) if part == dst or part.is_relative_to(dst)):
            raise ValueError(f'{name}: symlink in staging path {path!r}')
        if dest.exists():
            raise ValueError(f'{name}: staging file already exists {path!r}')
        dest.write_bytes(ordinary[path] if member.isfile() else ordinary[links[path]])
    return len(ordinary) + len(links)


def stage(cache:Path,out:Path):
    lock=json.loads((ROOT/'manifest/plugins.json').read_text());verify_lock(lock)
    if out.is_symlink():raise ValueError('unsafe plugin staging root')
    out.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for p in lock['plugins']:
        repo,commit,name=p['repo'],p['commit'],p['name']
        local=cache/name
        if not (local/'HEAD').is_file():
            local.mkdir(parents=True,exist_ok=True)
            git('init','--bare',str(local))
        # Network is never needed if the exact object is already cached.
        if subprocess.run(['git','--git-dir='+str(local),'cat-file','-e',commit+'^{commit}'],capture_output=True).returncode:
            git('--git-dir='+str(local),'fetch','--no-tags','--depth','1',f'https://github.com/{repo}.git',commit)
        got=git('--git-dir='+str(local),'rev-parse',commit+'^{tree}')
        if got!=p['tree']:raise ValueError(f'{name}: Git tree mismatch {got}')
        raw=subprocess.run(['git','--git-dir='+str(local),'archive','--format=tar',commit],check=True,capture_output=True).stdout
        dst=out/('zinit' if name=='zinit' else f'plugins/{name}')
        if dst.is_symlink():raise ValueError(f'{name}: symlink staging directory')
        dst.mkdir(parents=True,exist_ok=True)
        count=extract_plugin_archive(raw,dst,name)
        manifest.append({'name':name,'source':repo,'commit':commit,'tree':got,'files':count,'archiveSha256':hashlib.sha256(raw).hexdigest()})
    (out/'plugins-provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'AST_OFFLINE_ZINIT_PASS plugins={len(manifest)}')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path(os.getenv('STATIC_TOOLS_CACHE',str(Path.home()/'.cache/arm64-static-tools-module')))/'plugins')
    x=parser.parse_args();stage(x.cache,x.out)
if __name__=='__main__':main()
