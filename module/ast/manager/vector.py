"""Vector/LSPosed offline SQLite inspector and version-qualified rescue writes.

Writes are restricted to Vector's reviewed Database.kt DB_VERSION=5 layout.
Never uses the Android daemon CLI in recovery or guesses old LSPosed schema.
Every write requires typed confirmation by the caller, a consistent verified
pre-write backup, a true recovery environment, and one SQLite transaction.
"""
from __future__ import annotations
import os
from contextlib import closing
import re
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote
from .common import Refused, protect_leaf, require_recovery, safe_dir

DEFAULT_CONFIG = Path('/data/adb/lspd/config')
DEFAULT_BACKUPS = Path('/data/adb/arm64-static-tools/backups')
DB_NAME = 'modules_config.db'
DB_VERSION = 5
MAX_DB = 512 * 1024 * 1024
PACKAGE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z')
TARGET = re.compile(r'(?:system|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\Z')
# Reviewed from JingMatrix/Vector daemon Database.kt (DB_VERSION 5).
REQUIRED_COLUMNS = {
    'modules': ('mid','module_pkg_name','apk_path','enabled','auto_include'),
    'scope': ('mid','app_pkg_name','user_id'),
    'auto_include': ('mid','user_id'),
    'configs': ('module_pkg_name','user_id','group','key','data'),
}
ALLOWED_EXTRA_TABLES = {'android_metadata'}


def databases(folder: Path = DEFAULT_CONFIG) -> list[Path]:
    if not folder.is_dir():return []
    safe_dir(folder)
    result=[]
    for entry in sorted(folder.iterdir()):
        if entry.suffix.lower() in ('.db','.sqlite','.sqlite3'):
            protect_leaf(entry)
            if entry.is_file() and entry.stat().st_size<=MAX_DB:result.append(entry)
    return result


def _uri(path:Path, mode:str) -> str:
    return 'file:'+quote(str(path),safe='/')+'?mode='+mode


def _check_path(path:Path) -> Path:
    path=Path(os.path.abspath(path))
    safe_dir(path.parent)
    protect_leaf(path)
    if not path.is_file():raise Refused('Missing Vector SQLite database')
    s=path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_size>MAX_DB or s.st_nlink!=1:
        raise Refused('Unsafe Vector database file')
    for suffix in ('-wal','-shm','-journal'):
        side=Path(str(path)+suffix)
        protect_leaf(side)
        if side.exists() and not side.is_file():raise Refused('Unsafe SQLite sidecar')
    return path


def _qualify_v5(con:sqlite3.Connection) -> None:
    """Fail closed on schema drift; do not assume enabled+pkg columns suffice."""
    if con.execute('PRAGMA user_version').fetchone()[0]!=DB_VERSION:
        raise Refused('Vector database is not reviewed version 5; read-only mode')
    rows=con.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    tables={name for name,kind in rows if kind=='table'}
    if (not set(REQUIRED_COLUMNS)<=tables or
            tables-set(REQUIRED_COLUMNS)-ALLOWED_EXTRA_TABLES):
        raise Refused('Unknown Vector v5 table inventory')
    if any(kind=='trigger' or kind=='view' for name,kind in rows):
        raise Refused('Unexpected Vector database trigger or view')
    info={}
    for table,required in REQUIRED_COLUMNS.items():
        cols=con.execute('PRAGMA table_info("'+table+'")').fetchall()
        names=tuple(col[1] for col in cols)
        if names!=required:
            raise Refused('Vector v5 column inventory mismatch: '+table)
        info[table]=cols
    # SQLite's declared types, NOT NULL requirements and primary-key identity
    # are part of the reviewed v5 layout, not merely its column names.
    required_types={
        'modules': ('INTEGER','TEXT','TEXT','BOOLEAN','BOOLEAN'),
        'scope': ('INTEGER','TEXT','INTEGER'),
        'auto_include': ('INTEGER','INTEGER'),
        'configs': ('TEXT','INTEGER','TEXT','TEXT','BLOB'),
    }
    required_not_null={
        'modules': (1,2), 'scope': (1,2), 'auto_include': (0,1),
        'configs': (0,1,2,3,4),
    }
    for table,columns in info.items():
        if tuple(str(c[2]).upper() for c in columns)!=required_types[table]:
            raise Refused('Vector v5 declared type mismatch: '+table)
        if any(int(columns[i][3])!=1 for i in required_not_null[table]):
            raise Refused('Vector v5 NOT NULL constraint missing: '+table)
    if info['modules'][0][5]!=1 or [x[5] for x in info['scope']]!=[1,2,3]:
        raise Refused('Vector v5 primary key mismatch')
    if [x[5] for x in info['auto_include']]!=[1,2]:
        raise Refused('Vector v5 auto_include key mismatch')
    if [x[5] for x in info['configs']]!=[1,2,3,4,0]:
        raise Refused('Vector v5 config key mismatch')
    # The v5 daemon checks both Boolean columns; preserve that invariant.
    modules_ddl=con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='modules'").fetchone()[0]
    normalized=re.sub(r'\s+','',modules_ddl).lower()
    if 'check(enabledin(0,1))' not in normalized or 'check(auto_includein(0,1))' not in normalized:
        raise Refused('Vector v5 enabled/auto_include CHECK constraints missing')
    indexes=con.execute('PRAGMA index_list("modules")').fetchall()
    if not any(idx[2] and [col[2] for col in con.execute('PRAGMA index_info("'+idx[1]+'")')]==['module_pkg_name']
               for idx in indexes):
        raise Refused('Vector module package uniqueness not proven')
    for table,from_col,to_col in [('scope','mid','mid'),('auto_include','mid','mid'),
                                  ('configs','module_pkg_name','module_pkg_name')]:
        foreign=con.execute('PRAGMA foreign_key_list("'+table+'")').fetchall()
        if not any(r[2]=='modules' and r[3]==from_col and r[4]==to_col and r[6]=='CASCADE' for r in foreign):
            raise Refused('Vector v5 foreign key missing: '+table)
    if con.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise Refused('Vector v5 foreign key violation')
    if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':
        raise Refused('Vector database integrity failure')
    bad=con.execute('SELECT mid FROM modules WHERE enabled NOT IN (0,1) OR enabled IS NULL LIMIT 1').fetchone()
    if bad:raise Refused('Vector module enabled state invalid')


def _read_modules(con:sqlite3.Connection) -> list[dict]:
    result=[]
    for mid,pkg,state in con.execute('SELECT mid,module_pkg_name,enabled FROM modules ORDER BY module_pkg_name LIMIT 2000'):
        result.append({'id':mid,'package':str(pkg),'enabled':bool(state)})
    return result


def inspect_db(path:Path) -> dict:
    path=_check_path(path)
    con=sqlite3.connect(_uri(path,'ro'),uri=True,timeout=2)
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('PRAGMA busy_timeout=2000')
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise Refused('Vector SQLite integrity failure')
        version=con.execute('PRAGMA user_version').fetchone()[0]
        tables=[r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        simple={'modules','scope'}<=set(tables)
        modules=[];qualified=False;reason='unrecognized schema'
        if 'modules' in tables and {'module_pkg_name','enabled'}<= {c[1] for c in con.execute('PRAGMA table_info("modules")')}:
            modules=[{'package':str(a),'enabled':bool(b)} for a,b in con.execute(
                'SELECT module_pkg_name,enabled FROM modules ORDER BY module_pkg_name LIMIT 2000')]
        try:_qualify_v5(con);qualified=True;reason='Vector v5 qualified'
        except Refused as e:reason=str(e)
        scopes=[]
        if qualified:
            scopes=[{'package':str(pkg),'target':str(app),'user_id':int(uid)} for pkg,app,uid in con.execute(
                'SELECT m.module_pkg_name,s.app_pkg_name,s.user_id FROM scope s JOIN modules m ON m.mid=s.mid ORDER BY m.module_pkg_name,s.user_id,s.app_pkg_name LIMIT 5000')]
        return {'path':str(path),'integrity':'ok','user_version':version,'tables':tables,
                'modules':modules,'scopes':scopes,'schema_recognized':bool(modules) or simple,
                'write_qualified':qualified,'qualification_reason':reason,'read_only':True}
    except sqlite3.DatabaseError as e:
        raise Refused('Vector SQLite unreadable: '+str(e)[:150]) from e
    finally:con.close()


def inspect_all(config:Path=DEFAULT_CONFIG) -> list[dict]:
    return [inspect_db(x) for x in databases(config)]


def _validate_module(value:str) -> str:
    if not isinstance(value,str) or not PACKAGE.fullmatch(value) or len(value)>240 or value=='lspd':
        raise Refused('Invalid/non-mutable Xposed module package')
    return value


def _validate_target(value:str) -> str:
    if not isinstance(value,str) or not TARGET.fullmatch(value) or len(value)>240:
        raise Refused('Invalid target package; use system for the system process')
    return value


def _validate_user(value:int) -> int:
    if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=100000:
        raise Refused('Invalid Android user ID')
    return value


def _signature(path:Path) -> tuple:
    result=[]
    for name in (str(path),str(path)+'-wal'):
        candidate=Path(name)
        protect_leaf(candidate)
        if candidate.exists():
            stat_=candidate.stat()
            result.append((name,stat_.st_ino,stat_.st_size,stat_.st_mtime_ns))
        else:result.append((name,None))
    return tuple(result)


def mutate(config:Path, module:str, action:str, *, target:str|None=None,
           user_id:int=0, targets:list[str]|None=None, backups_root:Path=DEFAULT_BACKUPS,
           confirmed:bool=False, check_recovery:bool=True) -> dict:
    """Apply one reviewed operation with preflight, snapshot and SQLite atomicity.

    `check_recovery=False` is strictly for isolated unit-test fixtures.
    The installed frontend does not expose it.
    """
    if not confirmed:raise Refused('Typed recovery confirmation required')
    if check_recovery:require_recovery()
    pkg=_validate_module(module)
    user=_validate_user(user_id)
    if action not in ('enable','disable','scope-add','scope-remove','scope-set'):
        raise Refused('Unrecognized Vector operation')
    if action in ('scope-add','scope-remove'):
        target=_validate_target(target)
    elif target is not None:
        raise Refused('Unexpected scope target')
    if action=='scope-set':
        if targets is None or len(targets)>1000:
            raise Refused('Scope replacement requires explicit target list')
        selected=[_validate_target(x) for x in targets]
        if len(set(selected))!=len(selected):raise Refused('Duplicate scope target')
    elif targets is not None:raise Refused('Scope list only valid for scope-set')
    config=safe_dir(config)
    path=_check_path(config/DB_NAME)
    if (path.parent.stat().st_mode & 0o022) or (path.stat().st_mode & 0o022):
        raise Refused('Group/world-writable Vector database/config refused')
    if os.geteuid()==0 and (path.stat().st_uid!=0 or config.stat().st_uid!=0):
        raise Refused('Vector database/config must be owned by root')
    before=_signature(path)
    current=inspect_db(path)
    if not current['write_qualified']:
        raise Refused('Vector offline writes refused: '+current['qualification_reason'])
    if pkg not in {x['package'] for x in current['modules']}:
        raise Refused('Vector module not registered; recovery cannot install modules')
    # Refuse no-op operations before snapshot/retention. Recheck inside the
    # IMMEDIATE transaction after creating the backup.
    with closing(sqlite3.connect(_uri(path,'ro'),uri=True,timeout=2)) as pre:
        pre.execute('PRAGMA query_only=ON')
        _qualify_v5(pre)
        row=pre.execute('SELECT mid,enabled FROM modules WHERE module_pkg_name=?',(pkg,)).fetchone()
        if row is None:raise Refused('Unknown module before snapshot')
        mid=int(row[0])
        if action in ('enable','disable'):
            if int(row[1]) == (1 if action=='enable' else 0):
                raise Refused('Already in requested state')
        else:
            previous={r[0] for r in pre.execute('SELECT app_pkg_name FROM scope WHERE mid=? AND user_id=?',(mid,user))}
            if action=='scope-add' and target in previous:raise Refused('Scope target already present')
            if action=='scope-remove' and target not in previous:raise Refused('Scope target not present')
            if action=='scope-set' and set(selected)==previous:raise Refused('Scope unchanged')
    # Snapshot the *entire* config tree, WAL-consistently, before any mutation.
    from . import backups
    backup=backups.create_backup(config,backups_root,retain=5,check_recovery=check_recovery,prune=False)
    backups.verify_backup(backup)
    if before!=_signature(path):
        raise Refused('Vector source changed while creating backup; no edit performed')
    con=sqlite3.connect(_uri(path,'rw'),uri=True,timeout=2,isolation_level=None)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=2000')
        con.execute('BEGIN IMMEDIATE')
        _qualify_v5(con)
        row=con.execute('SELECT mid,enabled FROM modules WHERE module_pkg_name=?',(pkg,)).fetchone()
        if row is None:raise Refused('Vector module changed after backup')
        mid=int(row[0])
        if action in ('enable','disable'):
            enabled=1 if action=='enable' else 0
            if int(row[1])==enabled:raise Refused('Already in requested state; backup retained')
            cur=con.execute('UPDATE modules SET enabled=? WHERE mid=? AND enabled!=?',(enabled,mid,enabled))
            if cur.rowcount!=1:raise Refused('Vector module update race')
        else:
            old={r[0] for r in con.execute('SELECT app_pkg_name FROM scope WHERE mid=? AND user_id=?',(mid,user))}
            if action=='scope-add':
                if target in old:raise Refused('Scope target already present')
                con.execute('INSERT INTO scope(mid,app_pkg_name,user_id) VALUES(?,?,?)',(mid,target,user))
            elif action=='scope-remove':
                if target not in old:raise Refused('Scope target not present')
                cur=con.execute('DELETE FROM scope WHERE mid=? AND app_pkg_name=? AND user_id=?',(mid,target,user))
                if cur.rowcount!=1:raise Refused('Scope target update race')
            else:
                desired=set(selected)
                if desired==old:raise Refused('Scope unchanged; backup retained')
                for removed in sorted(old-desired):
                    con.execute('DELETE FROM scope WHERE mid=? AND app_pkg_name=? AND user_id=?',(mid,removed,user))
                for added in sorted(desired-old):
                    con.execute('INSERT INTO scope(mid,app_pkg_name,user_id) VALUES(?,?,?)',(mid,added,user))
        _qualify_v5(con)
        con.execute('COMMIT')
    except (sqlite3.Error,Refused) as e:
        if con.in_transaction:con.execute('ROLLBACK')
        if isinstance(e,sqlite3.Error):raise Refused('Vector SQLite transaction failed: '+str(e)[:120]) from e
        raise
    finally:con.close()
    after=inspect_db(path)
    if not after['write_qualified']:
        raise Refused('Post-write qualification failed; restore verified backup '+str(backup))
    try:
        pruned=backups.prune_backups(backups_root,retain=5)
        retention='verified; pruned '+str(pruned)+' older backups'
    except (Refused,OSError,ValueError) as err:
        # Do not mislabel a completed DB transaction as failed or retry it.
        retention='not completed: '+str(err)[:160]
    return {'action':action,'module':pkg,'target':target,'user_id':user,
            'backup':str(backup),'database':str(path),'result':'committed',
            'retention':retention}
