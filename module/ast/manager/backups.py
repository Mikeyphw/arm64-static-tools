"""Offline Vector config backup/restore with integrity validation and rollback.

Never use filesystem-only copies of live SQLite WAL databases. SQLite's
backup API generates a consistent snapshot. Restores require actual recovery
mode, explicit user consent, and preserve pre-restore rollback material.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from .common import Refused, protect_leaf, require_recovery, safe_dir
from .vector import DEFAULT_CONFIG

SNAPSHOT_RE = re.compile(r'vector-[0-9]{8}T[0-9]{6}Z(?:-[0-9]{2})?\Z')
MAX_FILES = 4096
MAX_BYTES = 512*1024*1024

def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def _items(root: Path):
    safe_dir(root)
    count = total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base)/name
            st=p.lstat()
            if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise Refused('Unsupported Vector config entry: '+str(p))
        for name in files:
            p=Path(base)/name
            st=p.lstat()
            count+=1;total+=st.st_size
            if count>MAX_FILES or total>MAX_BYTES:
                raise Refused('Backup size/file safety limit exceeded')
            yield p, p.relative_to(root), st

def _xattrs(p: Path) -> dict[str,str]:
    result={}
    try: keys=os.listxattr(p, follow_symlinks=False)
    except (AttributeError, OSError): return result
    for key in keys:
        if key != 'security.selinux': continue
        try: result[key]=base64.b64encode(os.getxattr(p,key,follow_symlinks=False)).decode('ascii')
        except OSError as ex: raise Refused(f'Cannot preserve SELinux context for {p}: {ex}') from ex
    return result

def _metadata(p:Path, st:os.stat_result, hashvalue:str='') -> dict:
    return {'size':st.st_size,'mode':stat.S_IMODE(st.st_mode),
            'uid':st.st_uid,'gid':st.st_gid,'sha256':hashvalue,'xattrs':_xattrs(p)}

def _sqlite_backup(src: Path, dst:Path):
    uri='file:'+quote(str(src),safe='/')+'?mode=ro'
    s=sqlite3.connect(uri,uri=True,timeout=5)
    try:
        started=time.monotonic()
        def progress(status,remaining,total):
            if time.monotonic()-started>20:
                raise Refused('SQLite backup exceeded bounded operation time')
        s.execute('PRAGMA query_only=ON')
        if s.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise Refused('Source SQLite integrity failure')
        d=sqlite3.connect(str(dst))
        try:
            s.backup(d,pages=64,sleep=.05,progress=progress)
            if d.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise Refused('Backup SQLite integrity failure')
            d.commit()
        finally:d.close()
    except sqlite3.DatabaseError as e:
        raise Refused('SQLite snapshot failure: '+str(e)[:120]) from e
    finally:s.close()

def _restore_attrs(path:Path, record:dict, *, strict:bool):
    os.chmod(path,int(record['mode']))
    if os.geteuid()==0:
        os.chown(path,int(record['uid']),int(record['gid']))
    for key,value in record.get('xattrs',{}).items():
        if key != 'security.selinux':raise Refused('Unsupported xattr in backup')
        try:os.setxattr(path,key,base64.b64decode(value),follow_symlinks=False)
        except OSError as ex:
            if strict:raise Refused('Cannot restore required SELinux label: '+str(ex)) from ex

def _private_root(path:Path) -> Path:
    path=Path(os.path.abspath(path))
    protect_leaf(path,kind='dir')
    safe_dir(path.parent)
    # A hostile parent may rename a private directory even without reading it.
    ps=path.parent.stat()
    if ps.st_mode & 0o022 and not (ps.st_mode & stat.S_ISVTX):
        raise Refused('Writable backup parent without sticky protection')
    if not path.exists():
        path.mkdir(mode=0o700)
    safe_dir(path)
    st=path.stat()
    if st.st_mode & 0o077 or (os.geteuid()==0 and st.st_uid!=0):
        raise Refused('Backup directory must be private and root-owned')
    return path

def verify_backup(backup:Path) -> dict:
    protect_leaf(backup,kind='dir');safe_dir(backup)
    manifest=backup/'manifest.json';protect_leaf(manifest)
    data=json.loads(manifest.read_text())
    if data.get('schema')!=1 or data.get('kind')!='ast-vector-config':raise Refused('Unrecognized backup format')
    if len(data.get('files',{}))>MAX_FILES:raise Refused('Too many backup files')
    total=0
    for rel,record in data['files'].items():
        if rel.startswith('/') or not rel or '..' in Path(rel).parts:raise Refused('Unsafe backup path')
        dest=backup/'config'/rel
        protect_leaf(dest)
        if not dest.is_file():raise Refused('Missing backup file '+rel)
        total+=dest.stat().st_size
        if total>MAX_BYTES or sha_file(dest)!=record.get('sha256'):
            raise Refused('Backup integrity mismatch '+rel)
    if set(x.relative_to(backup/'config').as_posix() for x,_,_ in _items(backup/'config')) != set(data['files']):
        raise Refused('Backup file inventory mismatch')
    directories=data.get('directories',{})
    if not isinstance(directories,dict) or '' not in directories:
        raise Refused('Missing directory metadata')
    for rel in directories:
        if rel.startswith('/') or '..' in Path(rel).parts:
            raise Refused('Unsafe directory metadata path')
        p=backup/'config'/rel
        protect_leaf(p,kind='dir')
        if not p.is_dir():raise Refused('Missing backup directory '+rel)
    return data

def list_backups(dest:Path) -> list[dict]:
    if not dest.is_dir():return []
    safe_dir(dest)
    result=[]
    for p in sorted(dest.iterdir(),reverse=True):
        if not SNAPSHOT_RE.fullmatch(p.name):continue
        try:
            d=verify_backup(p)
            result.append({'name':p.name,'files':len(d['files']),'created':d['created'],'valid':True})
        except (OSError, ValueError, Refused) as e:
            result.append({'name':p.name,'valid':False,'error':str(e)[:140]})
    return result

def prune_backups(root:Path, retain:int=5) -> int:
    """Prune only after the new backup AND caller's mutation are successful.

    Unknown/corrupt snapshots block rotation, never get silently deleted.
    """
    if not 1<=retain<=30:raise Refused('Unsupported retention')
    backup_root=_private_root(root)
    previous=[p for p in sorted(backup_root.iterdir(),reverse=True)
              if SNAPSHOT_RE.fullmatch(p.name) and p.is_dir() and not p.is_symlink()]
    if len(previous)<=retain:return 0
    # Verify every candidate first, so partial pruning cannot occur before
    # an integrity or format failure is discovered.
    for entry in previous:verify_backup(entry)
    for old in previous[retain:]:shutil.rmtree(old)
    fd=os.open(backup_root,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return len(previous)-retain

def create_backup(config:Path, backups:Path, *, retain:int=5, check_recovery:bool=True,
                  prune:bool=True) -> Path:
    if check_recovery:require_recovery()
    if retain<1 or retain>30:raise Refused('Unsupported retention')
    config=safe_dir(config)
    backup_root=_private_root(backups)
    temp=Path(tempfile.mkdtemp(prefix='.ast-creating-',dir=backup_root))
    try:
        (temp/'config').mkdir(mode=0o700)
        files={}
        directories={}
        for base, dirs, _files in os.walk(config,followlinks=False):
            path=Path(base)
            rel=path.relative_to(config).as_posix()
            if rel=='.':rel=''
            directories[rel]=_metadata(path,path.stat())
            for directory in dirs:
                protect_leaf(path/directory,kind='dir')
        for src,rel,st in _items(config):
            # SQLite '-wal' and '-shm' files must NOT be separately archived:
            # the consistent main-db snapshot has already incorporated WAL.
            if src.name.endswith(('-wal','-shm')):
                continue
            out=temp/'config'/rel
            out.parent.mkdir(parents=True,exist_ok=True)
            with src.open('rb') as probe:
                sqlite_format = probe.read(16)==b'SQLite format 3\x00'
            if sqlite_format or src.suffix.lower() in ('.db','.sqlite','.sqlite3'):
                _sqlite_backup(src,out)
            else:
                shutil.copyfile(src,out,follow_symlinks=False)
            _restore_attrs(out,_metadata(src,st),strict=False)
            files[rel.as_posix()]=_metadata(src,st,sha_file(out))
            files[rel.as_posix()]['size']=out.stat().st_size
        manifest={'schema':1,'kind':'ast-vector-config',
                  'created':datetime.now(timezone.utc).isoformat(),
                  'source':str(config),'files':files,'directories':directories}
        (temp/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        (temp/'manifest.json').chmod(0o600)
        verify_backup(temp)
        stamp=datetime.now(timezone.utc).strftime('vector-%Y%m%dT%H%M%SZ')
        final=backup_root/stamp
        for i in range(1,100):
            if not final.exists():break
            final=backup_root/(stamp+f'-{i:02d}')
        else: raise Refused('Backup naming collision')
        temp.rename(final)
        verify_backup(final)
        dirfd=os.open(backup_root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
        # A pre-mutation snapshot should not evict an older restore point until
        # its corresponding SQLite transaction commits successfully.
        if prune:
            prune_backups(backup_root,retain)
        return final
    finally:
        if temp.exists():shutil.rmtree(temp)

def restore_backup(backup:Path, config:Path, *, confirmed:bool=False,
                   check_recovery:bool=True) -> Path:
    if not confirmed:raise Refused('Restore requires explicit confirmation')
    if check_recovery:require_recovery()
    if not SNAPSHOT_RE.fullmatch(backup.name):
        raise Refused('Backup name is not an approved AST snapshot')
    _private_root(backup.parent)
    data=verify_backup(backup)
    config=safe_dir(config)
    parent=safe_dir(config.parent)
    staging=Path(tempfile.mkdtemp(prefix='.ast-restore-',dir=parent))
    rollback=parent/('config.ast-rollback-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if rollback.exists():raise Refused('Rollback name already occupied')
    try:
        for rel,record in data['files'].items():
            out=staging/rel
            out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(backup/'config'/rel,out,follow_symlinks=False)
            if sha_file(out)!=record['sha256']:raise Refused('Restore content mismatch '+rel)
            _restore_attrs(out,record,strict=True)
        # Directory modes/ownership/labels are as important as file labels.
        for rel,record in sorted(data['directories'].items(),
                                 key=lambda x: len(Path(x[0]).parts),reverse=True):
            dst=staging/rel
            dst.mkdir(parents=True,exist_ok=True)
            _restore_attrs(dst,record,strict=True)
        # No file mutation before all content is staged and validated.
        config.rename(rollback)
        try:staging.rename(config)
        except OSError:
            rollback.rename(config)
            raise
        dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
        return rollback  # Kept on disk; operator must explicitly clean it.
    finally:
        if staging.exists():shutil.rmtree(staging)
