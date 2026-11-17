"""AST R03: genuine Vector v5 schema, atomic recovery edits, backup gates,
and pinned static-Python internal alias extraction safety.
"""
from __future__ import annotations
import importlib.util
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'module/ast'))
from manager import vector, backups
from manager.common import Refused

SPEC=importlib.util.spec_from_file_location('ast_runtime',ROOT/'scripts/package_python_runtime.py')
RUNTIME=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(RUNTIME)


class Fixture(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.config=self.home/'config';self.config.mkdir(mode=0o700)
        self.backup_root=self.home/'backup'
        self.db=self.config/'modules_config.db'
        self.conn=sqlite3.connect(self.db)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
        CREATE TABLE modules (mid INTEGER PRIMARY KEY AUTOINCREMENT,
            module_pkg_name TEXT NOT NULL UNIQUE, apk_path TEXT NOT NULL,
            enabled BOOLEAN DEFAULT 0 CHECK(enabled IN (0,1)),
            auto_include BOOLEAN DEFAULT 0 CHECK(auto_include IN (0,1)));
        CREATE TABLE scope (mid INTEGER, app_pkg_name TEXT NOT NULL, user_id INTEGER NOT NULL,
            PRIMARY KEY(mid,app_pkg_name,user_id),
            CONSTRAINT scope_module_constraint FOREIGN KEY(mid) REFERENCES modules(mid) ON DELETE CASCADE);
        CREATE TABLE auto_include (mid INTEGER NOT NULL, user_id INTEGER NOT NULL,
            PRIMARY KEY(mid,user_id),
            CONSTRAINT auto_include_module_constraint FOREIGN KEY(mid) REFERENCES modules(mid) ON DELETE CASCADE);
        CREATE TABLE configs (module_pkg_name TEXT NOT NULL, user_id INTEGER NOT NULL,
            `group` TEXT NOT NULL, `key` TEXT NOT NULL, data BLOB NOT NULL,
            PRIMARY KEY(module_pkg_name,user_id,`group`,`key`),
            CONSTRAINT config_module_constraint FOREIGN KEY(module_pkg_name) REFERENCES modules(module_pkg_name) ON DELETE CASCADE);
        CREATE INDEX configs_idx ON configs(module_pkg_name,user_id);
        PRAGMA user_version=5;
        INSERT INTO modules(module_pkg_name,apk_path,enabled) VALUES('com.example.one','/data/app/one.apk',1);
        INSERT INTO modules(module_pkg_name,apk_path,enabled) VALUES('com.example.two','/data/app/two.apk',0);
        INSERT INTO scope(mid,app_pkg_name,user_id) VALUES(1,'com.example.target',0);
        INSERT INTO scope(mid,app_pkg_name,user_id) VALUES(1,'com.example.work',10);
        ''')
        self.conn.commit();self.conn.close()

    def mutate(self, action, *, module='com.example.one', **kwargs):
        return vector.mutate(self.config,module,action,backups_root=self.backup_root,
                             confirmed=True,check_recovery=False,**kwargs)

    def state(self):
        c=sqlite3.connect(self.db)
        try:
            return (c.execute('SELECT module_pkg_name,enabled FROM modules ORDER BY module_pkg_name').fetchall(),
                    c.execute('SELECT mid,app_pkg_name,user_id FROM scope ORDER BY mid,app_pkg_name,user_id').fetchall())
        finally:c.close()


class VectorV5Tests(Fixture):
    def test_qualified_v5_schema_and_scope_listing(self):
        d=vector.inspect_db(self.db)
        self.assertEqual(d['user_version'],5)
        self.assertTrue(d['write_qualified'])
        self.assertEqual([x['package'] for x in d['modules']],['com.example.one','com.example.two'])
        self.assertEqual(len(d['scopes']),2)

    def test_enable_disable_with_backup_then_verify(self):
        before=self.state()
        result=self.mutate('disable')
        self.assertEqual(result['result'],'committed')
        saved=Path(result['backup'])
        self.assertTrue(saved.exists())
        self.assertEqual(backups.verify_backup(saved)['kind'],'ast-vector-config')
        self.assertEqual(self.state()[0][0][1],0)
        self.assertTrue(vector.inspect_db(saved/'config'/'modules_config.db')['write_qualified'])
        saved_con=sqlite3.connect(saved/'config'/'modules_config.db')
        try:
            self.assertEqual(saved_con.execute(
                'SELECT enabled FROM modules WHERE module_pkg_name="com.example.one"').fetchone()[0],1)
        finally:saved_con.close()
        self.mutate('enable')
        self.assertEqual(before,self.state())

    def test_scope_changes_keep_other_users(self):
        self.mutate('scope-add',target='com.example.new')
        self.assertTrue((1,'com.example.new',0) in self.state()[1])
        self.mutate('scope-remove',target='com.example.new')
        self.assertFalse((1,'com.example.new',0) in self.state()[1])
        self.mutate('scope-set',targets=['com.example.changed'])
        scope=self.state()[1]
        self.assertEqual(scope,[(1,'com.example.changed',0),(1,'com.example.work',10)])
        self.mutate('scope-set',targets=[],user_id=0)
        self.assertEqual(self.state()[1],[(1,'com.example.work',10)])

    def test_unknown_versions_remain_read_only(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('PRAGMA user_version=4')
        before=self.state()
        d=vector.inspect_db(self.db)
        self.assertFalse(d['write_qualified'])
        with self.assertRaisesRegex(Refused,'read-only|refused|version'):
            self.mutate('disable')
        self.assertEqual(before,self.state())
        self.assertFalse(self.backup_root.exists())

    def test_lookalike_schema_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('ALTER TABLE modules ADD COLUMN mystery INTEGER')
        self.assertFalse(vector.inspect_db(self.db)['write_qualified'])
        with self.assertRaises(Refused):self.mutate('disable')

    def test_removed_enabled_constraint_refused(self):
        # A lookalike database with user_version=5 but weaker schema must
        # never be accepted just because its column names match.
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('PRAGMA writable_schema=ON')
            c.execute("UPDATE sqlite_master SET sql=replace(sql,'CHECK(enabled IN (0,1))','') WHERE name='modules'")
            c.execute('PRAGMA writable_schema=OFF')
            c.execute('PRAGMA schema_version=8')
        self.assertFalse(vector.inspect_db(self.db)['write_qualified'])
        with self.assertRaises(Refused):self.mutate('disable')

    def test_triggers_are_never_executed(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TRIGGER hostile AFTER UPDATE ON modules BEGIN DELETE FROM scope; END')
        with self.assertRaisesRegex(Refused,'schema|refused|trigger'):
            self.mutate('disable')

    def test_confirmation_and_recovery_required(self):
        with self.assertRaisesRegex(Refused,'confirmation'):
            vector.mutate(self.config,'com.example.one','disable',backups_root=self.backup_root,
                          confirmed=False,check_recovery=False)
        with self.assertRaisesRegex(Refused,'recovery'):
            vector.mutate(self.config,'com.example.one','disable',backups_root=self.backup_root,
                          confirmed=True,check_recovery=True)

    def test_bad_packages_never_create_backups(self):
        for bad in ['../etc','com.foo; DROP','lspd','com.foo/../../bar','']:
            with self.subTest(bad=bad),self.assertRaises(Refused):
                self.mutate('disable',module=bad)
        for bad in ['../../bad','com.bad; DROP','']:
            with self.subTest(bad=bad),self.assertRaises(Refused):
                self.mutate('scope-add',target=bad)
        for uid in (-1,100001,True,'10'):
            with self.subTest(uid=uid),self.assertRaises(Refused):
                self.mutate('scope-add',target='com.example.other',user_id=uid)
        self.assertFalse(self.backup_root.exists())

    def test_no_write_if_backup_fails(self):
        before=self.state()
        with patch.object(backups,'create_backup',side_effect=Refused('backup unavailable')):
            with self.assertRaisesRegex(Refused,'backup unavailable'):
                self.mutate('disable')
        self.assertEqual(before,self.state())

    def test_no_write_if_source_changes_during_backup(self):
        original=backups.create_backup
        def changed(*args,**kwargs):
            res=original(*args,**kwargs)
            with self.db.open('ab') as f:f.write(b' ')
            return res
        with patch.object(backups,'create_backup',side_effect=changed):
            with self.assertRaisesRegex(Refused,'changed while creating backup'):
                self.mutate('disable')
        self.assertEqual(self.state()[0][0][1],1)

    def test_invalid_state_is_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('PRAGMA ignore_check_constraints=ON')
            c.execute('UPDATE modules SET enabled=2 WHERE mid=1')
        self.assertFalse(vector.inspect_db(self.db)['write_qualified'])
        with self.assertRaises(Refused):self.mutate('disable')

    def test_duplicate_scope_and_noop_refuse_without_edit(self):
        with self.assertRaises(Refused):self.mutate('scope-add',target='com.example.target')
        with self.assertRaises(Refused):self.mutate('enable')
        self.assertEqual(self.state()[0][0][1],1)

    def test_symlink_database_rejected(self):
        real=self.config/'real.db'
        self.db.rename(real)
        self.db.symlink_to(real)
        with self.assertRaises(Refused):self.mutate('disable')

    def test_preserves_backup_recovery_restore_contract(self):
        snapshot=self.mutate('disable')['backup']
        rollback=backups.restore_backup(Path(snapshot),self.config,confirmed=True,check_recovery=False)
        self.assertTrue(rollback.exists())
        self.assertEqual(self.state()[0][0][1],1)

    def test_noop_does_not_rotate_backups(self):
        for _ in range(5):backups.create_backup(self.config,self.backup_root,retain=30,check_recovery=False)
        before={p.name for p in self.backup_root.iterdir()}
        with self.assertRaisesRegex(Refused,'Already in requested state'):
            self.mutate('enable')
        self.assertEqual(before,{p.name for p in self.backup_root.iterdir()})

    def test_failed_transaction_keeps_old_backup_history(self):
        for _ in range(5):backups.create_backup(self.config,self.backup_root,retain=30,check_recovery=False)
        previous={p.name for p in self.backup_root.iterdir()}
        original=vector._qualify_v5
        seen=[0]
        def fail_on_transaction(con):
            seen[0]+=1
            if seen[0]==3:raise Refused('transaction-level schema refusal')
            return original(con)
        with patch.object(vector,'_qualify_v5',side_effect=fail_on_transaction):
            with self.assertRaisesRegex(Refused,'transaction-level'):
                self.mutate('disable')
        self.assertEqual(self.state()[0][0][1],1)
        after={p.name for p in self.backup_root.iterdir()}
        self.assertTrue(previous <= after)
        self.assertEqual(len(after),6)

    def test_successful_mutation_prunes_only_after_commit(self):
        for _ in range(5):backups.create_backup(self.config,self.backup_root,retain=30,check_recovery=False)
        result=self.mutate('disable')
        self.assertEqual(result['result'],'committed')
        self.assertIn('pruned 1',result['retention'])
        self.assertEqual(len(backups.list_backups(self.backup_root)),5)


class PythonAliasTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        (self.root/'bin').mkdir()
        (self.root/'lib').mkdir()
        (self.root/'bin/python3.12').write_bytes(b'ELF-stub')
        (self.root/'lib/pydoc.py').write_text('hello')

    def test_sibling_python_alias(self):
        dst=self.root/'bin/python3'
        RUNTIME.materialize_python_links(self.root,[(dst,'python3.12')])
        self.assertEqual(dst.read_bytes(),b'ELF-stub')
        self.assertFalse(dst.is_symlink())

    def test_legitimate_parent_relative_file_alias(self):
        dst=self.root/'bin/pydoc3'
        RUNTIME.materialize_python_links(self.root,[(dst,'../lib/pydoc.py')])
        self.assertEqual(dst.read_text(),'hello')

    def test_external_symlink_escape_rejected(self):
        for target in ('../../etc/passwd','/etc/passwd','../..','',r'..\\evil'):
            with self.subTest(target=target),self.assertRaises(RUNTIME.Refused):
                RUNTIME.materialize_python_links(self.root,[(self.root/'bin/no',target)])

    def test_safe_symlink_chain_is_materialized(self):
        RUNTIME.materialize_python_links(self.root,[(self.root/'bin/python3','python3.11'),
                (self.root/'bin/python3.11','python3.12')])
        self.assertEqual((self.root/'bin/python3').read_bytes(),b'ELF-stub')
        self.assertEqual((self.root/'bin/python3.11').read_bytes(),b'ELF-stub')

    def test_cyclic_and_dangling_symlink_chain_rejected(self):
        with self.assertRaises(RUNTIME.Refused):
            RUNTIME.materialize_python_links(self.root,[(self.root/'bin/a','b'),
                (self.root/'bin/b','a')])
        with self.assertRaises(RUNTIME.Refused):
            RUNTIME.materialize_python_links(self.root,[(self.root/'bin/nothing','absent')])

    def test_relative_directory_alias_is_materialized_safely(self):
        dst=self.root/'bin/libalias'
        RUNTIME.materialize_python_links(self.root,[(dst,'../lib')])
        self.assertEqual((dst/'pydoc.py').read_text(),'hello')
        self.assertFalse(dst.is_symlink())

    def test_directory_recursion_refused(self):
        with self.assertRaises(RUNTIME.Refused):
            RUNTIME.materialize_python_links(self.root,[(self.root/'lib/recurse','..')])

    def test_preexisting_alias_target_refused(self):
        (self.root/'bin/python3').write_text('existing')
        with self.assertRaises(RUNTIME.Refused):
            RUNTIME.materialize_python_links(self.root,[(self.root/'bin/python3','python3.12')])

    def test_source_symlink_nested_directory_refused(self):
        (self.root/'lib/link').symlink_to('pydoc.py')
        with self.assertRaises(RUNTIME.Refused):
            RUNTIME.materialize_python_links(self.root,[(self.root/'bin/libalias','../lib')])


class PackageZipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('ast_zip_verify',ROOT/'scripts/verify_module_zip.py')
        cls.verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.verify)

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.path=self.root/'module.zip'
        self.entries={name:b'fixture' for name in self.verify.REQUIRED}
        self.entries['module.prop']=b'id=arm64_static_tools\nversion=0.5.0\nversionCode=5\n'
        fake=bytearray(64);fake[:4]=b'\x7fELF';fake[4]=2;fake[18:20]=(183).to_bytes(2,'little')
        self.entries['ast/runtime/python/bin/python3']=bytes(fake)

    def make(self, extra=None, mode=None):
        import zipfile
        with zipfile.ZipFile(self.path,'w') as z:
            for name, data in {**self.entries,**(extra or {})}.items():
                info=zipfile.ZipInfo(name)
                info.create_system=3
                permissions=mode.get(name,0o755) if mode else 0o755
                info.external_attr=(0o100000|permissions)<<16
                z.writestr(info,data)

    def test_valid_minimal_runtime_fixture(self):
        self.make()
        self.assertEqual(self.verify.verify(self.path)['files'],len(self.entries))

    def test_missing_python_refused(self):
        self.entries.pop('ast/runtime/python/bin/python3')
        self.make()
        with self.assertRaisesRegex(self.verify.Refused,'Missing required'):
            self.verify.verify(self.path)

    def test_symlink_refused(self):
        import zipfile
        self.make()
        with zipfile.ZipFile(self.path,'a') as z:
            info=zipfile.ZipInfo('ast/alias')
            info.create_system=3
            info.external_attr=(0o120777<<16)
            z.writestr(info,'../../etc/passwd')
        with self.assertRaisesRegex(self.verify.Refused,'Symlink'):
            self.verify.verify(self.path)

    def test_bytecode_refused(self):
        self.make({'ast/manager/__pycache__/main.pyc':b'host bytecode'})
        with self.assertRaisesRegex(self.verify.Refused,'bytecode'):
            self.verify.verify(self.path)

    def test_traversal_refused(self):
        self.make({'../escape':b'unsafe'})
        with self.assertRaisesRegex(self.verify.Refused,'Unsafe ZIP'):
            self.verify.verify(self.path)

    def test_python_architecture_refused(self):
        self.entries['ast/runtime/python/bin/python3']=b'not an ELF'
        self.make()
        with self.assertRaisesRegex(self.verify.Refused,'not ELF64 AArch64'):
            self.verify.verify(self.path)

    def test_missing_executable_bit_refused(self):
        self.make(mode={'ast/runtime/python/bin/python3':0o644})
        with self.assertRaisesRegex(self.verify.Refused,'executable bit'):
            self.verify.verify(self.path)

class NativeTerminalCLITests(Fixture):
    def test_vector_list_can_run_without_terminal(self):
        import subprocess
        p=subprocess.run([sys.executable,str(ROOT/'module/ast/manager/main.py'),
               '--config',str(self.config),'--backups',str(self.backup_root),'vector','list'],
               capture_output=True,text=True,env={**os.environ,'NO_COLOR':'1','TERM':'dumb'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('com.example.one',p.stdout)
        self.assertIn('com.example.target',p.stdout)

    def test_vector_mutation_refused_without_tty(self):
        import subprocess
        p=subprocess.run([sys.executable,str(ROOT/'module/ast/manager/main.py'),
               '--config',str(self.config),'--backups',str(self.backup_root),
               'vector','disable','com.example.one'],capture_output=True,text=True,
               env={**os.environ,'NO_COLOR':'1','TERM':'dumb'})
        self.assertEqual(p.returncode,2)
        self.assertIn('Typed confirmation required',p.stderr)
        self.assertEqual(self.state()[0][0][1],1)

    def test_cli_refuses_scope_without_target(self):
        import subprocess
        p=subprocess.run([sys.executable,str(ROOT/'module/ast/manager/main.py'),
                '--config',str(self.config),'vector','scope-add','com.example.one'],
                capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertIn('Exactly one scope target',p.stderr)


class HostedPackageContractTests(unittest.TestCase):
    def test_exact_lock_package_job(self):
        text=(ROOT/'.github/workflows/package.yml').read_text()
        block=text.split('  package:',1)[1].split('  update-report:',1)[0]
        self.assertIn('make fetch',block)
        self.assertIn('make package',block)
        self.assertNotIn('make update',block)
        self.assertIn('github.event.pull_request.head.sha || github.sha',block)

    def test_update_discovery_is_separate_read_only_job(self):
        text=(ROOT/'.github/workflows/package.yml').read_text()
        report=text.split('  update-report:',1)[1]
        self.assertIn("github.event_name == 'schedule'",report)
        self.assertIn('make update',report)
        self.assertNotIn('git push',report)
        self.assertNotIn('gh release',report)
        self.assertIn('upstream-update-review',report)

    def test_pull_request_is_first_class_event(self):
        text=(ROOT/'.github/workflows/package.yml').read_text()
        self.assertIn('  pull_request:',text)
        self.assertIn('  push:',text)

if __name__=='__main__':unittest.main()
