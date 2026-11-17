#!/usr/bin/env python3
"""Package only hash-pinned ARM64 static CPython + pure-Python wheels.

Runs on Linux packaging host. Never runs/downloads in Android or recovery.
No source build, pip invocation, dependency solver, executable code from wheels
or unreviewed binary. Full python-build-standalone tar.zst is required.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'manifest/python-runtime.json'
SHA=re.compile(r'[0-9a-f]{64}\Z')
LIMIT=300*1024*1024

class Refused(RuntimeError):pass

def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def load_lock():
    d=json.loads(LOCK.read_text())
    if d.get('schema')!=1 or d['python'].get('expected_static') is not True:
        raise Refused('Malformed runtime lock')
    if not d['python']['asset'].endswith('-musl-noopt+static-full.tar.zst'):
        raise Refused('Only full static musl archive allowed')
    if not SHA.fullmatch(d['python']['sha256']):raise Refused('Missing Python SHA256 pin')
    for wheel in d['wheels']:
        if not wheel['asset'].endswith('-py3-none-any.whl') or not SHA.fullmatch(wheel['sha256']):
            raise Refused('Unqualified wheel lock')
    if len({x['project'].casefold() for x in d['wheels']})!=4:raise Refused('Wheels incomplete/duplicated')
    return d

def download(url:str,path:Path, expected:str,offline:bool):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise Refused('Cache symlink refused')
    if path.exists() and digest(path)==expected:return
    if offline:raise Refused('Missing pinned cached asset: '+path.name)
    fd,temp=tempfile.mkstemp(prefix='.ast-dl-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as dst, urllib.request.urlopen(url, timeout=90) as resp:
            total=0
            while True:
                data=resp.read(1024*1024)
                if not data:break
                total+=len(data)
                if total>LIMIT:raise Refused('Download exceeds 300 MiB limit')
                dst.write(data)
        if digest(Path(temp))!=expected:raise Refused('Upstream asset SHA256 mismatch: '+path.name)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def secure_member(path:str,prefix:str):
    name=PurePosixPath(path)
    if name.is_absolute() or '..' in name.parts or not path.startswith(prefix):
        raise Refused('Unsafe archive path: '+path)
    return name

def materialize_python_links(out:Path, symlinks:list[tuple[Path,str]]):
    """Materialize legitimate in-root aliases, never install filesystem links."""
    # Legitimate Python archives can contain chained aliases such as
    # python -> python3 -> python3.12 or pydoc -> pydoc3 -> pydoc3.12.
    # Resolve the complete alias graph in the archive namespace, with an
    # explicit depth/cycle limit, before writing any aliases. Materialize only
    # verified in-tree regular files or bounded nonrecursive directories.
    aliases={}
    for dst,link in symlinks:
        relative=dst.relative_to(out).as_posix()
        if (relative in aliases or not link or link.startswith('/')
                or '\\' in link or '\x00' in link):
            raise Refused('Unsafe or duplicate Python symlink')
        aliases[relative]=link

    def resolve_alias(relative:str) -> Path:
        seen=set()
        for _ in range(16):
            if relative in seen:raise Refused('Cyclic Python symlink chain')
            seen.add(relative)
            link=aliases.get(relative)
            if link is None:return out.joinpath(*relative.split('/'))
            next_name=posixpath.normpath(posixpath.join(posixpath.dirname(relative),link))
            if (next_name in ('.','..') or next_name.startswith('../')
                    or next_name.startswith('/') or not next_name):
                raise Refused('External Python symlink target')
            relative=next_name
        raise Refused('Python symlink chain too deep')

    resolved={}
    for name in aliases:
        target=resolve_alias(name)
        dest=out.joinpath(*name.split('/'))
        if (dest.exists() or dest.is_symlink() or
                not target.resolve().is_relative_to(out.resolve())):
            raise Refused('Unsafe Python symlink destination')
        if not ((target.is_file() or target.is_dir()) and not target.is_symlink()):
            raise Refused('Dangling/unsupported Python symlink')
        resolved[name]=target

    for name,target in resolved.items():
        dst=out.joinpath(*name.split('/'))
        if target.is_file():
            if target.stat().st_size>125*1024*1024:
                raise Refused('Oversized Python symlink target')
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,dst,follow_symlinks=False)
        else:
            if (dst==out or target==out or dst.is_relative_to(target)
                    or target.is_relative_to(dst)):
                raise Refused('Cyclic Python directory symlink')
            count=0;size=0
            for root,dirs,files in os.walk(target,followlinks=False):
                for part in dirs+files:
                    node=Path(root)/part
                    if node.is_symlink():raise Refused('Nested Python directory symlink')
                for part in files:
                    node=Path(root)/part
                    if not node.is_file():raise Refused('Unexpected Python directory entry')
                    count+=1;size+=node.stat().st_size
                    if count>5000 or size>180*1024*1024:
                        raise Refused('Oversized Python directory alias')
            shutil.copytree(target,dst,symlinks=False)

def extract_cpython(archive:Path,out:Path):
    if not shutil.which('zstd'):raise Refused('zstd host decompressor required')
    # Never execute the archive. Reject devices/hardlinks and escaping symlinks.
    p=subprocess.Popen(['zstd','-dc',str(archive)],stdout=subprocess.PIPE)
    symlinks=[];bytes_total=0;count=0
    try:
        with tarfile.open(fileobj=p.stdout,mode='r|') as tar:
            for member in tar:
                name=member.name.removeprefix('./')
                if not name.startswith('python/install/'):
                    continue
                target=secure_member(name,'python/install/')
                rel=PurePosixPath(*target.parts[2:])
                if not rel.parts:continue
                dst=out.joinpath(*rel.parts)
                if member.isdir():dst.mkdir(parents=True,exist_ok=True)
                elif member.isfile():
                    count+=1;bytes_total+=member.size
                    if count>24000 or bytes_total>850*1024*1024 or member.size>125*1024*1024:
                        raise Refused('Oversized Python archive')
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    stream=tar.extractfile(member)
                    if stream is None:raise Refused('Invalid archive member')
                    with dst.open('xb') as f:shutil.copyfileobj(stream,f,1024*1024)
                    dst.chmod(0o755 if member.mode & 0o111 else 0o644)
                elif member.issym():symlinks.append((dst,member.linkname))
                else:raise Refused('Disallowed Python archive entry '+name)
        if p.wait()!=0:raise Refused('Python zstd decode failed')
        materialize_python_links(out,symlinks)
    finally:
        if p.poll() is None:p.kill();p.wait()
    # Important: build's Python aliases can differ; only expose a stable path
    # after validating that the copied interpreter is a real static ELF.
    bin_dir=out/'bin'
    candidates=[p for p in bin_dir.glob('python3*') if p.is_file()]
    if not candidates:raise Refused('Static Python executable missing')
    executable=next((x for x in candidates if x.name=='python3'),candidates[0])
    if executable.name!='python3':shutil.copy2(executable,bin_dir/'python3')
    verify_elf(bin_dir/'python3')
    return bin_dir/'python3'

def verify_elf(path:Path):
    blob=path.read_bytes()[:64]
    if blob[:4]!=b'\x7fELF' or blob[4]!=2 or int.from_bytes(blob[18:20],'little')!=183:
        raise Refused('Expected ELF64 little-endian AArch64 Python')
    if not shutil.which('readelf'):raise Refused('readelf host qualifier required')
    prog=subprocess.run(['readelf','-lW',str(path)],capture_output=True,text=True,check=True).stdout
    dynamic=subprocess.run(['readelf','-dW',str(path)],capture_output=True,text=True).stdout
    if 'INTERP' in prog or '(NEEDED)' in dynamic:
        raise Refused('Python not truly static (INTERP/DT_NEEDED present)')

def install_wheel(path:Path,site:Path):
    with zipfile.ZipFile(path) as z:
        for item in z.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or not name.parts:
                raise Refused('Wheel traversal refused')
            if ((item.external_attr>>16)&0o170000)==stat.S_IFLNK:
                raise Refused('Wheel symlink refused')
            if item.is_dir():continue
            if item.file_size>10*1024*1024:raise Refused('Oversized wheel member')
            if name.parts[0].endswith('.data'):
                raise Refused('Wheel .data install relocation unsupported')
            # Dist-info retained for provenance. Native shared libraries banned.
            if name.suffix in ('.so','.pyd','.dll','.dylib'):
                raise Refused('Native library in pure-Python wheel')
            dest=site.joinpath(*name.parts)
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as src,dest.open('xb') as dst:shutil.copyfileobj(src,dst)
            dest.chmod(0o644)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cache',type=Path,default=Path(os.getenv('STATIC_TOOLS_CACHE',str(Path.home()/'.cache/arm64-static-tools-module')))/'python-runtime')
    p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    d=load_lock();a.out.mkdir(parents=True,exist_ok=True)
    if any(a.out.iterdir()):raise Refused('Runtime staging output must be empty')
    pyth=d['python']
    url=f'https://github.com/{pyth["project"]}/releases/download/{pyth["release"]}/{pyth["asset"]}'
    archive=a.cache/pyth['asset'];download(url,archive,pyth['sha256'],a.offline)
    extract_cpython(archive,a.out)
    site=a.out/'site-packages';site.mkdir()
    for wheel in d['wheels']:
        url=f'https://files.pythonhosted.org/packages/' # resolved using PyPI JSON only to find canonical filename
        metadata_url=f'https://pypi.org/pypi/{wheel["project"]}/{wheel["version"]}/json'
        cached=a.cache/wheel['asset']
        if not cached.exists() or digest(cached)!=wheel['sha256']:
            if a.offline:raise Refused('Pinned wheel missing from cache: '+wheel['asset'])
            with urllib.request.urlopen(metadata_url,timeout=30) as resp: metadata=json.load(resp)
            assets=[x for x in metadata['urls'] if x.get('filename')==wheel['asset'] and
                    x.get('digests',{}).get('sha256')==wheel['sha256']]
            if len(assets)!=1:raise Refused('PyPI lock does not match official wheel digest')
            url=assets[0]['url']
            if not url.startswith('https://files.pythonhosted.org/'):
                raise Refused('Unexpected PyPI wheel hostname')
            download(url,cached,wheel['sha256'],a.offline)
        install_wheel(cached,site)
    (a.out/'AST_RUNTIME_PROVENANCE.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
    print('AST_STATIC_PYTHON_PACKAGE_OK interpreter='+str(a.out/'bin/python3'))

if __name__=='__main__':
    try:main()
    except (Refused,OSError,KeyError,ValueError) as e:raise SystemExit('AST_RUNTIME_REFUSED '+str(e))
