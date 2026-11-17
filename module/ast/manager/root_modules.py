"""KernelSU/Magisk/APatch module inspection and deliberate recovery rescue.

Never runs service scripts or guesses a root manager; native KernelSU CLI
is used only if its exact binary is accessible, otherwise marker semantics.
"""
from __future__ import annotations
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from .common import Refused, atomic_marker, protect_leaf, require_id, safe_dir, require_recovery

KSU_MODULE_ROOT = Path('/data/adb/modules')

@dataclass(frozen=True)
class RootModule:
    identifier: str
    name: str
    version: str
    description: str
    disabled: bool
    pending_removal: bool

def _props(path: Path) -> dict[str, str]:
    protect_leaf(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise Refused(f'Unsafe module metadata: {path}')
    data = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if '=' in line:
            key, val = line.split('=', 1)
            if key in ('id','name','version','description'):
                data[key] = val[:240].replace('\x1b', '')
    return data

def list_modules(root: Path = Path('/data/adb/modules')) -> list[RootModule]:
    if not root.exists(): return []
    safe_dir(root)
    modules = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        try:
            require_id(entry.name)
            safe_dir(entry)
            prop = entry/'module.prop'
            if not prop.is_file(): continue
            p = _props(prop)
            if p.get('id', entry.name) != entry.name:
                # Some managers carry different module.prop identities; never
                # use untrusted metadata as a path or mutation argument.
                continue
            for marker in ('disable','remove'):
                protect_leaf(entry/marker)
            modules.append(RootModule(entry.name, p.get('name', entry.name),
                    p.get('version', '?'), p.get('description',''),
                    (entry/'disable').exists(), (entry/'remove').exists()))
        except (OSError, Refused):
            continue
    return modules

def native_ksu() -> Path | None:
    binary = Path('/data/adb/ksud')
    if binary.is_file() and not binary.is_symlink() and os.access(binary, os.X_OK):
        return binary
    return None

def change_module(root: Path, identifier: str, action: str, *,
                  confirmed: bool = False, recovery_check: bool = True,
                  use_native: bool = True) -> str:
    """Atomic per-marker fallback or documented ksud interface. No silent fallback after ksud errors."""
    require_id(identifier)
    if action not in ('enable','disable','remove','undo-remove'):
        raise Refused('Unsupported root-module operation')
    if not confirmed: raise Refused('Explicit confirmation required')
    if recovery_check: require_recovery()
    safe_dir(root)
    module = root/identifier
    safe_dir(module)
    known = {m.identifier: m for m in list_modules(root)}
    if identifier not in known: raise Refused('Unknown or unsafe module identifier')
    ksu = native_ksu() if use_native and root == KSU_MODULE_ROOT else None
    if ksu and action in ('enable','disable','remove'):
        # KernelSU's CLI uses `uninstall` for a staged removal. This operation
        # is never retried via direct marker fallback if the CLI fails.
        native_action = {'remove':'uninstall'}.get(action,action)
        p = subprocess.run([str(ksu), 'module', native_action, identifier],
                           check=False, timeout=25, capture_output=True, text=True)
        if p.returncode:
            raise Refused('KernelSU native operation failed: '+p.stderr[:160])
        return 'ksud'
    marker, present = {
        'enable':('disable',False), 'disable':('disable',True),
        'remove':('remove',True), 'undo-remove':('remove',False),
    }[action]
    atomic_marker(module,marker,present)
    return 'recovery-marker'
