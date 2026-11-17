#!/usr/bin/env python3
"""Validate generated AST recovery ZIP safety without executing ARM64 binaries.

Runs in the packaging host after the source-pinned downloads have been staged.
"""
from __future__ import annotations
import argparse
import os
from pathlib import PurePosixPath, Path
import stat
import zipfile

REQUIRED={
    'module.prop','customize.sh','service.sh','uninstall.sh',
    'ast/entrypoint.sh','ast/install-entrypoint.sh',
    'ast/runtime/python/bin/python3',
    'ast/manager/main.py','ast/manager/vector.py','ast/manager/backups.py',
    'ast/runtime/python/site-packages/rich/__init__.py',
    'ast/runtime/python/site-packages/pygments/__init__.py',
    'ast/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh',
    'ast/zinit/zinit.zsh','system/bin/zsh','system/bin/fzf',
}
MAX_TOTAL=1024*1024*1024
MAX_MEMBER=150*1024*1024

class Refused(RuntimeError):pass


def verify(path:Path):
    if path.is_symlink() or not path.is_file():raise Refused('Missing or linked module ZIP')
    total=0;seen=set();found=set();mode={}
    with zipfile.ZipFile(path) as z:
        for item in z.infolist():
            name=item.filename
            if (not name or '\\' in name or name.startswith('/') or
                 any(part in ('..','.') for part in name.rstrip('/').split('/')) or
                 not all(name.rstrip('/').split('/'))):
                raise Refused('Unsafe ZIP entry '+repr(name))
            normalized=name.rstrip('/')
            if normalized in seen:raise Refused('Duplicate ZIP entry '+normalized)
            seen.add(normalized)
            kind=(item.external_attr>>16)&0o170000
            if kind==stat.S_IFLNK:raise Refused('Symlink in module ZIP '+name)
            if kind not in (0,stat.S_IFREG,stat.S_IFDIR):
                raise Refused('Special file in module ZIP '+name)
            if item.is_dir():continue
            if item.file_size>MAX_MEMBER:raise Refused('Oversized ZIP member '+name)
            total+=item.file_size
            if total>MAX_TOTAL:raise Refused('Oversized module ZIP')
            if name.endswith(('.pyc','.pyo')) or '/__pycache__/' in name:
                raise Refused('Host Python bytecode in recovery module '+name)
            found.add(name)
            mode[name]=(item.external_attr>>16)&0o777
        missing=REQUIRED-found
        if missing:raise Refused('Missing required runtime/module files: '+', '.join(sorted(missing)))
        for name in ('system/bin/zsh','ast/runtime/python/bin/python3',
                     'ast/entrypoint.sh','customize.sh'):
            if not (mode[name]&0o111):raise Refused('Runtime executable bit missing '+name)
        with z.open('ast/runtime/python/bin/python3') as f:elf=f.read(20)
        if elf[:4]!=b'\x7fELF' or elf[4]!=2 or int.from_bytes(elf[18:20],'little')!=183:
            raise Refused('Packaged Python is not ELF64 AArch64')
        with z.open('module.prop') as f:prop=f.read(4096).decode('utf-8','strict')
        if 'id=arm64_static_tools\n' not in prop+'\n':raise Refused('Wrong module ID')
    return {'files':len(found),'uncompressed_bytes':total}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('path',type=Path)
    args=ap.parse_args()
    r=verify(args.path)
    print(f'AST_PACKAGE_ZIP_VERIFIED files={r["files"]} bytes={r["uncompressed_bytes"]}')

if __name__=='__main__':
    try:main()
    except (Refused,OSError,ValueError,zipfile.BadZipFile) as e:
        raise SystemExit('AST_PACKAGE_ZIP_REFUSED '+str(e))
