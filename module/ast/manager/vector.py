"""Read-only offline Vector/LSPosed SQLite inspection; NO schema writes."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote
from .common import Refused, protect_leaf, safe_dir

DEFAULT_CONFIG = Path('/data/adb/lspd/config')

def databases(folder: Path = DEFAULT_CONFIG) -> list[Path]:
    if not folder.is_dir(): return []
    safe_dir(folder)
    out=[]
    for x in sorted(folder.iterdir()):
        if x.suffix.lower() in ('.db','.sqlite','.sqlite3'):
            protect_leaf(x)
            if x.is_file() and x.stat().st_size <= 512*1024*1024:
                out.append(x)
    return out

def inspect_db(path: Path) -> dict:
    protect_leaf(path)
    safe_dir(path.parent)
    if not path.is_file(): raise Refused('Missing Vector database')
    if path.stat().st_size > 512*1024*1024: raise Refused('Oversized SQLite database')
    # mode=ro reads the live WAL state rather than ignoring uncheckpointed data.
    uri='file:'+quote(str(path),safe='/')+'?mode=ro'
    con=sqlite3.connect(uri,uri=True,timeout=2)
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('PRAGMA busy_timeout=2000')
        check=con.execute('PRAGMA quick_check').fetchone()[0]
        if check != 'ok': raise Refused('SQLite integrity check failed: '+str(check)[:120])
        schema=con.execute('PRAGMA user_version').fetchone()[0]
        rows=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        tables=[r[0] for r in rows if isinstance(r[0],str)]
        modules=[]
        # Qualified read-only compatibility case: modules contains exactly the
        # module_pkg_name and enabled columns, as seen in LSPosed/Vector DBs.
        # Unknown schemas do not get guessed SQL; R03 adds version-bound edits.
        if 'modules' in tables:
            cols={r[1] for r in con.execute('PRAGMA table_info("modules")')}
            if {'module_pkg_name','enabled'} <= cols:
                modules=[{'package':str(a),'enabled':bool(b)} for a,b in
                         con.execute('SELECT module_pkg_name, enabled FROM "modules" ORDER BY module_pkg_name LIMIT 2000')]
        return {'path':str(path),'integrity':'ok','user_version':schema,
                'tables':tables,'modules':modules,
                'schema_recognized':bool(modules) or ('modules' in tables and
                       {'module_pkg_name','enabled'} <=
                       {r[1] for r in con.execute('PRAGMA table_info("modules")')}),
                'read_only':True}
    except sqlite3.DatabaseError as ex:
        raise Refused('Unusable Vector SQLite database: '+str(ex)[:140]) from ex
    finally: con.close()

def inspect_all(config: Path = DEFAULT_CONFIG) -> list[dict]:
    return [inspect_db(x) for x in databases(config)]
