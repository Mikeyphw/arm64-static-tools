"""Root-safe path, confirmation and filesystem helpers."""
from __future__ import annotations
import os
import re
import stat
from pathlib import Path

class Refused(RuntimeError):
    pass

MODULE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')

def require_id(value: str) -> str:
    if not isinstance(value, str) or not MODULE_ID.fullmatch(value) or value in ('.', '..'):
        raise Refused('Invalid module identifier')
    return value

def safe_dir(path: Path, *, must_exist: bool = True) -> Path:
    path = Path(os.path.abspath(path))
    parts = list(path.parents)[::-1] + [path]
    for p in parts:
        try:
            s = p.lstat()
        except FileNotFoundError:
            if must_exist:
                raise Refused(f'Missing directory: {p}')
            continue
        if stat.S_ISLNK(s.st_mode):
            raise Refused(f'Symlink component refused: {p}')
        if not stat.S_ISDIR(s.st_mode):
            raise Refused(f'Non-directory component: {p}')
    return path

def protect_leaf(path: Path, *, kind: str = 'file') -> None:
    try: s = path.lstat()
    except FileNotFoundError: return
    if stat.S_ISLNK(s.st_mode): raise Refused(f'Symlink refused: {path}')
    if kind == 'file' and not stat.S_ISREG(s.st_mode):
        raise Refused(f'Non-regular file refused: {path}')
    if kind == 'dir' and not stat.S_ISDIR(s.st_mode):
        raise Refused(f'Non-directory refused: {path}')

def require_recovery() -> None:
    # AST_MODE alone is not a security boundary; actual recovery markers required.
    if os.getenv('AST_MODE') != 'recovery' or not any(Path(x).exists() for x in
                          ('/sbin/recovery','/twres','/etc/recovery.fstab','/tmp/recovery.log')):
        raise Refused('Write operations require a verified recovery environment')

def atomic_marker(module: Path, marker: str, present: bool) -> None:
    if marker not in ('disable', 'remove'):
        raise Refused('Marker not allowlisted')
    safe_dir(module)
    fd = os.open(module, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                 getattr(os, 'O_NOFOLLOW', 0))
    try:
        if present:
            try:
                newfd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=fd)
            except FileExistsError:
                existing = os.stat(marker, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode):
                    raise Refused('Non-regular existing state marker')
            else:
                os.close(newfd)
        else:
            try:
                existing = os.stat(marker, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(existing.st_mode):
                    raise Refused('Non-regular existing state marker')
                os.unlink(marker, dir_fd=fd)
            except FileNotFoundError: pass
        os.fsync(fd)
    finally:
        os.close(fd)
