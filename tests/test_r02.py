"""R02 unit, failure-mode and trust-boundary tests (not device evidence)."""
from __future__ import annotations
import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'module/ast'))
from manager import common, root_modules, vector, backups

SPEC=importlib.util.spec_from_file_location('ast_package_python_runtime',ROOT/'scripts/package_python_runtime.py')
RUNTIME=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)

class R02Temp(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory();self.addCleanup(self.work.cleanup)
        self.root=Path(self.work.name)
        self.modules=self.root/'modules';self.modules.mkdir()
        self.config=self.root/'lspd'/'config';self.config.mkdir(parents=True)
        self.backups=self.root/'backups';self.backups.mkdir(mode=0o700)
        self.module('first')
    def module(self,name,disabled=False):
        p=self.modules/name;p.mkdir()
        (p/'module.prop').write_text(f'id={name}\nname={name.capitalize()}\nversion=1.2\ndescription=Test module\n')
        if disabled:(p/'disable').touch()
        return p
    def db(self,name='modules.db',*,recognized=True):
        p=self.config/name
        c=sqlite3.connect(p)
        if recognized:
            c.execute('CREATE TABLE modules(module_pkg_name TEXT PRIMARY KEY, enabled INTEGER NOT NULL)')
            c.execute("INSERT INTO modules VALUES('com.example.foo',1)")
        else:c.execute('CREATE TABLE unknown(id INTEGER)')
        c.commit();c.close();return p

class RootModuleTests(R02Temp):
    def test_list_matches_directories(self):
        x=root_modules.list_modules(self.modules)
        self.assertEqual([(m.identifier,m.name,m.disabled) for m in x],[('first','First',False)])
    def test_module_id_validation(self):
        for bad in ('../x','/data/adb','x/y','x\n','', '.','..'):
            with self.subTest(bad=bad),self.assertRaises(common.Refused):common.require_id(bad)
    def test_disable_enable_marker_fallback(self):
        self.assertEqual(root_modules.change_module(self.modules,'first','disable',confirmed=True,recovery_check=False,use_native=False),'recovery-marker')
        self.assertTrue((self.modules/'first/disable').exists())
        root_modules.change_module(self.modules,'first','enable',confirmed=True,recovery_check=False,use_native=False)
        self.assertFalse((self.modules/'first/disable').exists())
    def test_stage_remove_and_undo(self):
        root_modules.change_module(self.modules,'first','remove',confirmed=True,recovery_check=False,use_native=False)
        self.assertTrue((self.modules/'first/remove').exists())
        root_modules.change_module(self.modules,'first','undo-remove',confirmed=True,recovery_check=False,use_native=False)
        self.assertFalse((self.modules/'first/remove').exists())
    def test_confirmation_required(self):
        with self.assertRaisesRegex(common.Refused,'confirmation'):
            root_modules.change_module(self.modules,'first','disable',recovery_check=False)
        self.assertFalse((self.modules/'first/disable').exists())
    def test_recovery_required_even_if_env_says_recovery(self):
        with patch.dict(os.environ,{'AST_MODE':'recovery'}), self.assertRaisesRegex(common.Refused,'verified recovery'):
            root_modules.change_module(self.modules,'first','disable',confirmed=True,use_native=False)
    def test_symlink_marker_not_removed(self):
        p=self.modules/'first/disable';p.symlink_to(self.root/'target')
        with self.assertRaises(common.Refused):
            root_modules.change_module(self.modules,'first','enable',confirmed=True,recovery_check=False,use_native=False)
    def test_symlink_module_skipped(self):
        (self.modules/'bad').symlink_to(self.modules/'first')
        self.assertEqual(len(root_modules.list_modules(self.modules)),1)
    def test_malformed_identity_skipped(self):
        (self.modules/'first/module.prop').write_text('id=evil\n')
        self.assertEqual(root_modules.list_modules(self.modules),[])
    def test_invalid_marker_action_refuses(self):
        with self.assertRaises(common.Refused):
            root_modules.change_module(self.modules,'first','rm -rf',confirmed=True,recovery_check=False)
    def test_native_failure_no_fallback(self):
        fake=self.root/'fake-ksud';fake.write_text('#!/bin/sh\nexit 3\n');fake.chmod(0o755)
        with patch.object(root_modules,'native_ksu',return_value=fake), patch.object(root_modules,'KSU_MODULE_ROOT',self.modules):
            with self.assertRaisesRegex(common.Refused,'native operation failed'):
                root_modules.change_module(self.modules,'first','disable',confirmed=True,recovery_check=False)
        self.assertFalse((self.modules/'first/disable').exists())

class VectorTests(R02Temp):
    def test_recognized_schema_read_only(self):
        path=self.db()
        before=path.read_bytes()
        result=vector.inspect_db(path)
        self.assertTrue(result['read_only']);self.assertEqual(result['modules'][0]['package'],'com.example.foo')
        self.assertEqual(path.read_bytes(),before)
    def test_unrecognized_schema_refuses_guessing(self):
        path=self.db(recognized=False)
        d=vector.inspect_db(path)
        self.assertEqual(d['modules'],[]);self.assertFalse(d['schema_recognized'])
    def test_corrupt_sqlite_refuses(self):
        p=self.config/'bad.db';p.write_bytes(b'not sqlite')
        with self.assertRaises(common.Refused):vector.inspect_db(p)
    def test_symlink_database_refuses(self):
        path=self.db();(self.config/'link.db').symlink_to(path)
        with self.assertRaises(common.Refused):vector.databases(self.config)
    def test_wal_state_is_observed_without_mutating(self):
        p=self.config/'live.db'
        con=sqlite3.connect(p)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE modules(module_pkg_name TEXT PRIMARY KEY, enabled INTEGER)')
        con.commit()
        con.execute("INSERT INTO modules VALUES('com.example.wal',1)");con.commit()
        try:
            result=vector.inspect_db(p)
            self.assertEqual(result['modules'][0]['package'],'com.example.wal')
        finally:con.close()

class BackupTests(R02Temp):
    def test_create_verify_snapshot(self):
        self.db();(self.config/'settings.json').write_text('{"enabled":true}')
        dst=backups.create_backup(self.config,self.backups,check_recovery=False)
        self.assertEqual(len(backups.verify_backup(dst)['files']),2)
        self.assertEqual(len(backups.list_backups(self.backups)),1)
    def test_restore_keeps_original(self):
        self.db();(self.config/'readme.txt').write_text('before')
        snap=backups.create_backup(self.config,self.backups,check_recovery=False)
        (self.config/'readme.txt').write_text('modified')
        rollback=backups.restore_backup(snap,self.config,confirmed=True,check_recovery=False)
        self.assertEqual((self.config/'readme.txt').read_text(),'before')
        self.assertEqual((rollback/'readme.txt').read_text(),'modified')
    def test_refuse_unconfirmed_restore(self):
        self.db();snap=backups.create_backup(self.config,self.backups,check_recovery=False)
        with self.assertRaisesRegex(common.Refused,'confirmation'):
            backups.restore_backup(snap,self.config,check_recovery=False)
    def test_corrupted_backup_is_detected(self):
        (self.config/'notes').write_text('hello')
        p=backups.create_backup(self.config,self.backups,check_recovery=False)
        (p/'config/notes').write_text('tampered')
        with self.assertRaises(common.Refused):backups.verify_backup(p)
    def test_unsafe_source_symlink(self):
        (self.config/'x').symlink_to('/etc/passwd')
        with self.assertRaises(common.Refused):backups.create_backup(self.config,self.backups,check_recovery=False)
    def test_retention_after_success(self):
        (self.config/'notes').write_text('hello')
        results=[]
        for i in range(6):
            results.append(backups.create_backup(self.config,self.backups,check_recovery=False))
        self.assertEqual(len(backups.list_backups(self.backups)),5)
        self.assertTrue(results[-1].is_dir())
    def test_no_rotation_on_failed_new_backup(self):
        (self.config/'notes').write_text('hello')
        old=backups.create_backup(self.config,self.backups,check_recovery=False)
        (self.config/'evil').symlink_to('/etc/passwd')
        with self.assertRaises(common.Refused):backups.create_backup(self.config,self.backups,check_recovery=False)
        self.assertTrue(old.exists())
    def test_unsafe_backup_manifest_path_refused(self):
        (self.config/'notes').write_text('hello')
        old=backups.create_backup(self.config,self.backups,check_recovery=False)
        p=old/'manifest.json';d=json.loads(p.read_text());d['files']['../escape']=d['files']['notes'];p.write_text(json.dumps(d))
        with self.assertRaises(common.Refused):backups.verify_backup(old)
    def test_root_is_private(self):
        self.backups.chmod(0o777)
        (self.config/'notes').write_text('hello')
        with self.assertRaises(common.Refused):backups.create_backup(self.config,self.backups,check_recovery=False)
    def test_sqlite_backup_wal_consistency(self):
        p=self.config/'state.db';c=sqlite3.connect(p);c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE a(x INTEGER)');c.commit();c.execute('INSERT INTO a VALUES(5)');c.commit()
        try:
            snap=backups.create_backup(self.config,self.backups,check_recovery=False)
            check=sqlite3.connect(snap/'config/state.db')
            self.assertEqual(check.execute('SELECT x FROM a').fetchone()[0],5)
            check.close()
            self.assertFalse((snap/'config/state.db-wal').exists())
        finally:c.close()

class RuntimeTests(unittest.TestCase):
    def test_pinned_runtime_lock(self):
        d=RUNTIME.load_lock();self.assertEqual(len(d['wheels']),4)
        self.assertIn('+static-full.tar.zst',d['python']['asset'])
        self.assertEqual(len(d['python']['sha256']),64)
    def test_reject_dynamic_runtime(self):
        # Using a temporary synthetic manifest to exercise the strict suffix.
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'lock.json';d=RUNTIME.load_lock();d['python']['asset']=d['python']['asset'].replace('+static','')
            p.write_text(json.dumps(d))
            with patch.object(RUNTIME,'LOCK',p),self.assertRaises(RUNTIME.Refused):RUNTIME.load_lock()
    def test_reject_bad_wheel_digest(self):
        with tempfile.TemporaryDirectory() as t:
            z=Path(t)/'bad.whl'
            with ZipFile(z,'w') as f:f.writestr('../escape','oops')
            with self.assertRaises(RUNTIME.Refused):RUNTIME.install_wheel(z,Path(t)/'site')
    def test_elf_arch(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'elf';p.write_bytes(b'not-elf')
            with self.assertRaises(RUNTIME.Refused):RUNTIME.verify_elf(p)
    def test_missing_offline_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);dst=p/'out';cache=p/'cache'
            r=subprocess.run([sys.executable,str(ROOT/'scripts/package_python_runtime.py'),
                 '--out',str(dst),'--cache',str(cache),'--offline'],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('AST_RUNTIME_REFUSED',r.stderr+r.stdout)
    def test_no_runtime_network_in_recovery_launcher(self):
        s=(ROOT/'module/ast/entrypoint.sh').read_text()
        self.assertIn('ast_python()',s)
        self.assertNotIn('curl ',s);self.assertNotIn('wget ',s)
        self.assertNotIn('pip install',s)

class CLITests(R02Temp):
    def test_doctor_plain_json_without_optional_rich(self):
        p=ROOT/'module/ast/manager/main.py'
        env=os.environ.copy();env['TERM']='dumb';env['NO_COLOR']='1';env['AST_MODE']='recovery'
        r=subprocess.run([sys.executable,str(p),'--config',str(self.config),'--backups',str(self.backups),'doctor','--json'],capture_output=True,text=True,env=env)
        self.assertEqual(r.returncode,0,msg=r.stderr)
        d=json.loads(r.stdout)
        self.assertFalse(d['color']);self.assertFalse(d['vector_writes_enabled'])
    def test_menu_requires_terminal(self):
        p=ROOT/'module/ast/manager/main.py'
        r=subprocess.run([sys.executable,str(p),'--config',str(self.config),'menu'],
                         stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,2);self.assertIn('TTY unavailable',r.stderr)
    def test_menu_refuses_real_stdin_tty_with_redirected_stdout(self):
        # Regression for native Devtool run in interactive Termux: capture_output
        # creates a stdout PIPE but otherwise inherits the foreground TTY.
        master,slave=os.openpty()
        try:
            p=ROOT/'module/ast/manager/main.py'
            r=subprocess.run([sys.executable,str(p),'--config',str(self.config),'menu'],
                             stdin=slave,capture_output=True,text=True,timeout=10)
        finally:
            os.close(slave);os.close(master)
        self.assertEqual(r.returncode,2);self.assertIn('TTY unavailable',r.stderr)
    def test_module_picker_refuses_redirected_stdout_with_stdin_tty(self):
        master,slave=os.openpty()
        try:
            p=ROOT/'module/ast/manager/main.py'
            r=subprocess.run([sys.executable,str(p),'--config',str(self.config),
                              '--modules',str(self.modules),'modules','disable'],
                             stdin=slave,capture_output=True,text=True,timeout=10)
        finally:
            os.close(slave);os.close(master)
        self.assertEqual(r.returncode,2);self.assertIn('TTY unavailable',r.stderr)
    def test_posix_recovery_shell(self):
        subprocess.run(['sh','-n',str(ROOT/'module/ast/entrypoint.sh')],check=True)
    def test_packaging_excludes_host_bytecode(self):
        sh=(ROOT/'scripts/package.sh').read_text()
        self.assertIn('name __pycache__',sh)
        self.assertIn("-name '*.pyc'",sh)
        purity=(ROOT/'scripts/check_repo_purity.py').read_text()
        self.assertIn('".pyc"',purity)
    def test_doc_preserves_terminal(self):
        readme=(ROOT/'README.md').read_text().lower();self.assertIn('terminal stays primary',readme)
        self.assertIn('ast --safe',readme)

if __name__=='__main__':unittest.main()
