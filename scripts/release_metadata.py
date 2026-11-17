#!/usr/bin/env python3
"""Generate/check stable root-manager update metadata from verified local artifacts.

No publication or network I/O. The release workflow alone publishes, after
validating the exact ZIP and monotonically increasing versionCode.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile, BadZipFile

NAME = 'arm64_static_tools'
REPO_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$')
VERSION_RE = re.compile(r'^[0-9]+(?:\.[0-9]+){1,3}$')


def props(data: str) -> dict[str,str]:
    result = {}
    for line in data.splitlines():
        if not line.strip() or line.startswith('#'):continue
        if '=' not in line: raise ValueError('Invalid module.prop line')
        key,value=line.split('=',1)
        if not key or key in result or not value or key.strip()!=key:
            raise ValueError('Invalid or duplicate module.prop key')
        result[key]=value
    return result


def verify_prop(s: str, repo: str|None=None):
    p=props(s)
    if p.get('id')!=NAME: raise ValueError('Wrong module id')
    if not VERSION_RE.fullmatch(p.get('version','')): raise ValueError('Invalid module version')
    try: vc=int(p['versionCode'])
    except (KeyError,ValueError):raise ValueError('Invalid versionCode') from None
    if vc <= 0 or str(vc)!=p['versionCode']:raise ValueError('Invalid versionCode')
    if repo:
        wanted=f'https://github.com/{repo}/releases/latest/download/update.json'
        if p.get('updateJson')!=wanted:raise ValueError('ZIP updateJson does not match release repository')
    return p


def digest(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def zip_module_prop(path:Path):
    with ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or any(n.startswith('/') or '..' in Path(n).parts or '\\' in n for n in names):
            raise ValueError('Unsafe module ZIP entries')
        if 'module.prop' not in names or 'customize.sh' not in names or 'system/bin/zsh' not in names \
           or 'ast/entrypoint.sh' not in names:
            raise ValueError('ZIP missing required module files')
        if sum(x.file_size for x in z.infolist())>1_000_000_000:
            raise ValueError('Oversized module ZIP')
        for entry in z.infolist():
            mode=(entry.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:raise ValueError('Symlink in module ZIP')
        if z.getinfo('module.prop').file_size>8192:raise ValueError('Oversized module.prop')
        return z.read('module.prop').decode('utf-8')


def make(repo:str, zip_path:Path, notes:Path, out:Path, current:Path|None=None):
    if not REPO_RE.fullmatch(repo) or repo.lower().endswith('/devtool'):
        raise ValueError('Invalid release repository identity')
    if not zip_path.is_file() or not notes.is_file() or not notes.read_text().strip():
        raise ValueError('Missing ZIP or non-empty changelog')
    prop=verify_prop(zip_module_prop(zip_path),repo)
    version=prop['version']; version_code=int(prop['versionCode'])
    if current:
        previous=json.loads(current.read_text())
        prior=int(previous['versionCode'])
        if version_code<=prior:raise ValueError('versionCode must increase; refusing downgrade/re-release')
    if zip_path.name!=f'arm64-static-tools-{version}.zip':raise ValueError('ZIP filename mismatch')
    release=f'https://github.com/{repo}/releases/download/v{quote(version)}'
    update={'version':version,'versionCode':version_code,
            'zipUrl':f'{release}/{quote(zip_path.name)}',
            'changelog':f'{release}/changelog.md'}
    out.mkdir(parents=True,exist_ok=True)
    (out/'update.json').write_text(json.dumps(update,indent=2)+'\n')
    (out/'changelog.md').write_bytes(notes.read_bytes())
    (out/(zip_path.name+'.sha256')).write_text(f'{digest(zip_path)}  {zip_path.name}\n')
    (out/'integrity.json').write_text(json.dumps({'zipSha256':digest(zip_path),
        'moduleId':NAME,'versionCode':version_code,'version':version},indent=2)+'\n')
    print(f'AST_UPDATE_METADATA_PASS {repo} v{version} code={version_code} sha256={digest(zip_path)}')
    return update


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',required=True)
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--notes',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    a=parser.parse_args()
    make(a.repo,a.zip,a.notes,a.out,a.previous)

if __name__=='__main__':main()
