#!/usr/bin/env python3
"""AST Recovery Manager. In-terminal Rich panels and fzf selection; never Textual."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# Standalone script path works without -m or an external Python installation.
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from manager import backups, root_modules, vector
    from manager.common import Refused
else:
    from . import backups, root_modules, vector
    from .common import Refused

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Confirm
    RICH=True
except ImportError:
    Console=Table=Panel=Confirm=None
    RICH=False

NO_COLOR=('NO_COLOR' in os.environ or os.getenv('CLICOLOR')=='0' or os.getenv('TERM')=='dumb')
ANSI_OK=sys.stdin.isatty() and sys.stdout.isatty() and not NO_COLOR
CONSOLE=Console(force_terminal=ANSI_OK, no_color=NO_COLOR, highlight=False) if RICH else None

def emit(s=''):
    if CONSOLE:CONSOLE.print(str(s),markup=False)
    else:print(s)

def heading(title:str):
    if CONSOLE:CONSOLE.print(Panel(title,subtitle='AST Recovery',border_style='cyan' if ANSI_OK else 'white'))
    else:print('\n=== '+title+' ===')

def table(rows:list[dict],columns:list[str]):
    if CONSOLE:
        t=Table(show_lines=False,header_style='bold cyan' if ANSI_OK else '')
        for k in columns:t.add_column(k)
        for row in rows:t.add_row(*(str(row.get(k,''))[:250] for k in columns))
        CONSOLE.print(t)
    else:
        print(' | '.join(columns))
        for row in rows:print(' | '.join(str(row.get(k,''))[:100] for k in columns))

def yes(prompt:str, *, expect:str='YES') -> bool:
    if not sys.stdin.isatty():return False
    emit(f'{prompt}\nType {expect} to confirm; anything else cancels.')
    try: return input('> ').strip()==expect
    except (EOFError,KeyboardInterrupt):return False

def options(title:str, values:list[tuple[str,str]]) -> str|None:
    if not sys.stdin.isatty():raise Refused('Interactive TTY unavailable; use read-only commands')
    # Arrow keys, search and Esc are delegated to the already pinned static
    # fzf binary; if it cannot use the recovery TTY, keep numbered prompts.
    fzf=Path(os.getenv('AST_ROOT','/data/adb/modules/arm64_static_tools'))/'system/bin/fzf'
    if ANSI_OK and fzf.is_file() and os.access(fzf,os.X_OK):
        lines=''.join(key+'\t'+label+'\n' for key,label in values)
        try:
            proc=subprocess.run([str(fzf),'--height=60%','--layout=reverse',
                  '--border','--prompt='+title+' > ', '--delimiter=\t',
                  '--with-nth=2..'],input=lines,text=True,capture_output=True,timeout=300)
            if proc.returncode==0:
                key=proc.stdout.strip().split('\t',1)[0]
                if key in {v for v,_ in values}:return key
            if proc.returncode in (1,130):return None
        except (OSError,subprocess.TimeoutExpired):pass
    heading(title)
    for i,(_,label) in enumerate(values,1):emit(f'  {i:2d}. {label}')
    emit('   0. Back to shell/menu')
    try:choice=input('Select > ').strip()
    except (KeyboardInterrupt,EOFError):return None
    if choice in ('0','','q','Q','ESC'):return None
    if not choice.isdecimal() or not 1<=int(choice)<=len(values):return None
    return values[int(choice)-1][0]

def choose_modules(modules:list[root_modules.RootModule], *, multi:bool=True) -> list[str]:
    if not modules:return []
    fzf=Path(os.environ.get('AST_ROOT','/data/adb/modules/arm64_static_tools'))/'system/bin/fzf'
    if ANSI_OK and fzf.is_file() and os.access(fzf,os.X_OK):
        args=[str(fzf),'--ansi','--border','--height=60%', '--prompt=Module > ',
              '--delimiter=\t','--with-nth=2..']
        if multi:args.insert(1,'--multi')
        lines=''.join(m.identifier+'\t'+m.name+' ['+('disabled' if m.disabled else 'enabled')+']\n' for m in modules)
        try:
            p=subprocess.run(args,input=lines,capture_output=True,text=True,timeout=300)
            if p.returncode==0:
                chosen=[x.split('\t',1)[0] for x in p.stdout.splitlines()]
                valid={m.identifier for m in modules}
                if all(x in valid for x in chosen):return chosen
            if p.returncode in (1,130):return []
        except (OSError,subprocess.TimeoutExpired):pass
    table([{'#':i,'ID':m.identifier,'Name':m.name,'State':'disabled' if m.disabled else 'enabled'}
           for i,m in enumerate(modules,1)],['#','ID','Name','State'])
    emit('Enter number'+('s separated by spaces' if multi else '')+'; empty cancels.')
    try:raw=input('Select > ').strip()
    except (EOFError,KeyboardInterrupt):return []
    parts=raw.split()
    if not multi and len(parts)>1:return []
    if not parts or any(not x.isdecimal() or not 1<=int(x)<=len(modules) for x in parts):return []
    return list(dict.fromkeys(modules[int(x)-1].identifier for x in parts))

def module_action(root:Path,action:str, *, ident:str|None=None,assume_yes:bool=False):
    ms=root_modules.list_modules(root)
    if not ms:
        emit('No safely identified root modules found');return
    names=[ident] if ident else choose_modules(ms)
    valid={m.identifier for m in ms}
    if not names:return
    if any(x not in valid for x in names):raise Refused('Unrecognized module ID')
    heading('Review pending changes')
    table([{'Module':x,'Action':action} for x in names],['Module','Action'])
    if assume_yes:
        raise Refused('Interactive confirmation cannot be bypassed for recovery mutations')
    phrase='DISABLE ALL' if action=='disable' and len(names)==len(ms) and len(ms)>1 else 'YES'
    if not yes('Root module mutation. Changes may affect boot; existing user files must be preserved.',expect=phrase):
        emit('Cancelled — no changes');return
    for x in names:
        how=root_modules.change_module(root,x,action,confirmed=True)
        emit(f'{x}: {action} ({how})')

def module_menu(root:Path):
    while True:
        action=options('KernelSU / Magisk / APatch modules',[
            ('list','List installed modules'),('enable','Enable selected'),
            ('disable','Disable selected'),('remove','Mark selected for removal'),
            ('undo-remove','Undo pending removal'),('rescue','Emergency: disable ALL modules')])
        if action is None:return
        if action=='list':
            table([{'ID':m.identifier,'Name':m.name,'Version':m.version,'State':'remove' if m.pending_removal else 'disabled' if m.disabled else 'enabled'}
                   for m in root_modules.list_modules(root)],['ID','Name','Version','State'])
        elif action=='rescue':
            ms=root_modules.list_modules(root)
            if not ms:continue
            heading('Emergency rescue: disable all modules')
            table([{'ID':m.identifier,'Name':m.name} for m in ms],['ID','Name'])
            if yes('ALL root modules will be disabled. Continue?',expect='DISABLE ALL'):
                for m in ms:
                    if not m.disabled:
                        how=root_modules.change_module(root,m.identifier,'disable',confirmed=True)
                        emit(f'{m.identifier}: disabled ({how})')
        else:module_action(root,action)

def vector_view(config:Path):
    details=vector.inspect_all(config)
    if not details:emit('No offline SQLite databases found in '+str(config));return
    for item in details:
        heading('Vector offline database · read-only')
        table([{'Property':'File','Value':item['path']},
               {'Property':'Integrity','Value':item['integrity']},
               {'Property':'Schema','Value':item['user_version']},
               {'Property':'Tables','Value':', '.join(item['tables'])},
               {'Property':'Recognized modules','Value':item['schema_recognized']}],['Property','Value'])
        if item['modules']:
            table([{'Package':x['package'],'State':'enabled' if x['enabled'] else 'disabled'}
                   for x in item['modules']],['Package','State'])
        else:emit('Module schema not qualified. Offline writes are disabled until R03.')

def backups_menu(config:Path, dest:Path):
    while True:
        action=options('Vector backups',[
            ('list','List and verify saved backups'),('create','Create consistent snapshot'),
            ('restore','Restore verified backup (recovery only)')])
        if action is None:return
        if action=='list':
            table(backups.list_backups(dest),['name','valid','created','files','error'])
        elif action=='create':
            if yes('Create an offline backup of '+str(config)+'?'):
                emit('Created: '+str(backups.create_backup(config,dest)))
        elif action=='restore':
            records=[x for x in backups.list_backups(dest) if x.get('valid')]
            if not records:emit('No valid backups');continue
            sel=options('Choose verified backup',[(r['name'],r['name']+' · '+r['created']) for r in records])
            if sel is None:continue
            preview=backups.verify_backup(dest/sel)
            emit(f'{sel}: {len(preview["files"])} files, created {preview["created"]}')
            table([{'File':name,'Bytes':meta['size'],'SHA256':meta['sha256'][:12]+'...'}
                   for name,meta in list(preview['files'].items())[:40]],['File','Bytes','SHA256'])
            for name in preview['files']:
                if Path(name).suffix in ('.db','.sqlite','.sqlite3'):
                    try:
                        details=vector.inspect_db(dest/sel/'config'/name)
                        if details['modules']:
                            table([{'Module':m['package'],'Enabled':m['enabled']}
                                   for m in details['modules'][:60]],['Module','Enabled'])
                    except Refused:pass
            if yes('Restore will replace Vector configuration; pre-restore tree is retained for rollback.',expect='RESTORE '+sel):
                emit('Rollback retained at '+str(backups.restore_backup(dest/sel,config,confirmed=True)))

def doctor(config:Path, dest:Path) -> dict:
    root=Path(os.environ.get('AST_ROOT','/data/adb/modules/arm64_static_tools'))
    runtime=root/'ast/runtime/python/bin/python3'
    result={'mode':os.environ.get('AST_MODE','unknown'),'static_python':str(runtime),
            'python_executable':sys.executable,'rich':RICH,'term':os.getenv('TERM',''),
            'color':ANSI_OK,'data_ready':Path('/data/adb').is_dir(),
            'ksud':bool(root_modules.native_ksu()),
            'vector_db_count':len(vector.databases(config)),
            'backup_count':len(backups.list_backups(dest)),
            'py2droid_detected':Path('/data/adb/py2droid/usr/bin/python3').is_file(),
            'offline':True,'vector_writes_enabled':False}
    return result

def dashboard(config:Path,dest:Path,modules:Path):
    while True:
        action=options('AST Recovery · terminal-first dashboard',[
            ('modules','Root module manager'),('vector','Vector/LSPosed · offline read-only'),
            ('backups','Five-backup manager'),('doctor','System diagnostics'),
            ('shell','Return to Zsh / shell')])
        if action in (None,'shell'):return
        try:
            if action=='modules':module_menu(modules)
            elif action=='vector':vector_view(config)
            elif action=='backups':backups_menu(config,dest)
            elif action=='doctor':table([{'Setting':k,'Value':str(v)} for k,v in doctor(config,dest).items()],['Setting','Value'])
        except (Refused,OSError,ValueError) as ex:emit('Refused: '+str(ex))

def main(argv=None) -> int:
    p=argparse.ArgumentParser(prog='ast',description='AST recovery terminal dashboard')
    p.add_argument('--config',default='/data/adb/lspd/config',help=argparse.SUPPRESS)
    p.add_argument('--backups',default=os.getenv('AST_BACKUPS','/data/adb/arm64-static-tools/backups'),help=argparse.SUPPRESS)
    p.add_argument('--modules',default='/data/adb/modules',help=argparse.SUPPRESS)
    sub=p.add_subparsers(dest='command')
    sub.add_parser('menu');a=sub.add_parser('modules');a.add_argument('action',nargs='?',default='menu',choices=('menu','list','enable','disable','remove','undo-remove'));a.add_argument('identifier',nargs='?')
    sub.add_parser('vector');b=sub.add_parser('backups');b.add_argument('action',nargs='?',default='menu',choices=('menu','list','create','restore'));b.add_argument('name',nargs='?')
    d=sub.add_parser('doctor');d.add_argument('--json',action='store_true');d.add_argument('--export',help='Write a minimal sanitized report to a new private file')
    x=p.parse_args(argv)
    config=Path(x.config);dest=Path(x.backups);modules=Path(x.modules)
    try:
        if x.command in (None,'menu'):dashboard(config,dest,modules)
        elif x.command=='modules':
            if x.action=='menu':module_menu(modules)
            elif x.action=='list':table([vars(m) for m in root_modules.list_modules(modules)],['identifier','name','version','disabled','pending_removal'])
            else:module_action(modules,x.action,ident=x.identifier)
        elif x.command=='vector':vector_view(config)
        elif x.command=='backups':
            if x.action=='menu':backups_menu(config,dest)
            elif x.action=='list':table(backups.list_backups(dest),['name','valid','created','files','error'])
            elif x.action=='create':
                if not yes('Create a consistent offline backup?'):return 2
                emit(str(backups.create_backup(config,dest)))
            elif x.action=='restore':
                if not x.name:raise Refused('Explicit backup name required')
                if not yes('Replace offline Vector config and retain rollback copy?',expect='RESTORE '+x.name):return 2
                emit(str(backups.restore_backup(dest/x.name,config,confirmed=True)))
        elif x.command=='doctor':
            report=doctor(config,dest)
            if x.json:print(json.dumps(report,indent=2,sort_keys=True))
            else:table([{'Setting':k,'Value':str(v)} for k,v in report.items()],['Setting','Value'])
            if x.export:
                target=Path(x.export)
                if target.exists() or target.is_symlink():raise Refused('Refusing to overwrite diagnostic report')
                target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as f:json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
    except (Refused, OSError, ValueError, sqlite3.DatabaseError) as exc:
        print('AST_REFUSED: '+str(exc),file=sys.stderr);return 2
    except KeyboardInterrupt:
        emit('Cancelled');return 130
    return 0

if __name__=='__main__':
    raise SystemExit(main())
