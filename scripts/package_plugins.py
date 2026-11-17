#!/usr/bin/env python3
"""Stage exact-git-tree offline Zinit sources. No unpinned plugin download."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import shutil
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

def stage(cache:Path,out:Path):
    lock=json.loads((ROOT/'manifest/plugins.json').read_text());verify_lock(lock)
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
        dst.mkdir(parents=True,exist_ok=True)
        count=0
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as z:
            for m in z:
                target=dst/m.name
                if m.name.startswith('/') or '..' in Path(m.name).parts or m.issym() or m.islnk() or not target.resolve().is_relative_to(dst.resolve()):
                    raise ValueError(f'{name}: unsafe archive entry')
                if m.isdir(): target.mkdir(parents=True,exist_ok=True);continue
                if not m.isfile():raise ValueError(f'{name}: unsupported type')
                if m.size>2_000_000:raise ValueError(f'{name}: oversized plugin file')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(z.extractfile(m).read())
                count+=1
        manifest.append({'name':name,'source':repo,'commit':commit,'tree':got,'files':count,'archiveSha256':hashlib.sha256(raw).hexdigest()})
    (out/'plugins-provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'AST_OFFLINE_ZINIT_PASS plugins={len(manifest)}')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path(os.getenv('STATIC_TOOLS_CACHE',str(Path.home()/'.cache/arm64-static-tools-module')))/'plugins')
    x=parser.parse_args();stage(x.cache,x.out)
if __name__=='__main__':main()
