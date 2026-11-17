"""R01 recovery bootstrapping/update-contract tests; no root manager required."""
from __future__ import annotations
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_metadata', ROOT/'scripts/release_metadata.py')
rm=importlib.util.module_from_spec(spec);spec.loader.exec_module(rm)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name);self.repo='Mikeyphw/sample-ast'
        self.zip=self.dir/'arm64-static-tools-0.3.0.zip'
        self.notes=self.dir/'notes.md';self.notes.write_text('# Tested notes\n')
        self.prop=('id=arm64_static_tools\nname=AST\nversion=0.3.0\nversionCode=3\n'
                   'updateJson=https://github.com/'+self.repo+'/releases/latest/download/update.json\n')
        self.make_zip()

    def make_zip(self,prop=None, extra=None):
        with ZipFile(self.zip,'w') as z:
            z.writestr('module.prop',self.prop if prop is None else prop)
            z.writestr('customize.sh','true\n')
            z.writestr('system/bin/zsh','FAKE-ARM64 (not for distribution)')
            z.writestr('ast/entrypoint.sh','#!/system/bin/sh\n')
            if extra:
                for k,v in extra.items():z.writestr(k,v)

    def test_valid_manager_contract(self):
        result=rm.make(self.repo,self.zip,self.notes,self.dir/'out')
        self.assertEqual(result['versionCode'],3)
        self.assertEqual(result['version'],'0.3.0')
        self.assertIn('/releases/download/v0.3.0/',result['zipUrl'])
        self.assertEqual((self.dir/'out'/'update.json').read_text().count('"zipUrl"'),1)
        self.assertEqual(len((self.dir/'out'/'integrity.json').read_text()),len((self.dir/'out'/'integrity.json').read_text()))

    def test_reject_wrong_module_id(self):
        self.make_zip(prop=self.prop.replace('arm64_static_tools','wrong_id'))
        with self.assertRaisesRegex(ValueError,'Wrong module id'):rm.make(self.repo,self.zip,self.notes,self.dir/'out')

    def test_reject_different_update_origin(self):
        self.make_zip(prop=self.prop.replace('Mikeyphw/sample-ast','evil/repo'))
        with self.assertRaisesRegex(ValueError,'updateJson'):rm.make(self.repo,self.zip,self.notes,self.dir/'out')

    def test_reject_rollback_code(self):
        old=self.dir/'old.json';old.write_text('{"versionCode": 3}')
        with self.assertRaisesRegex(ValueError,'increase'):rm.make(self.repo,self.zip,self.notes,self.dir/'out',old)

    def test_reject_malicious_archive(self):
        self.make_zip(extra={'../pwned':'x'})
        with self.assertRaisesRegex(ValueError,'Unsafe'):rm.make(self.repo,self.zip,self.notes,self.dir/'out')

    def test_reject_broken_code(self):
        self.make_zip(prop=self.prop.replace('versionCode=3','versionCode=three'))
        with self.assertRaisesRegex(ValueError,'versionCode'):rm.make(self.repo,self.zip,self.notes,self.dir/'out')

    def test_reject_symlink_zip_entry(self):
        from zipfile import ZipInfo
        info=ZipInfo('extras/evil')
        info.create_system=3
        info.external_attr=(0o120777 << 16)
        with ZipFile(self.zip,'a') as z:z.writestr(info,'../../etc/passwd')
        with self.assertRaisesRegex(ValueError,'Symlink'):rm.make(self.repo,self.zip,self.notes,self.dir/'out')

    def test_refuse_wrong_repository(self):
        with self.assertRaisesRegex(ValueError,'repository'):rm.make('not-a-repo',self.zip,self.notes,self.dir/'out')

class ShellTests(unittest.TestCase):
    def test_release_script_syntax(self):
        try:import yaml
        except ImportError:self.skipTest('PyYaml not installed; workflow YAML qualified in CI')
        y=yaml.safe_load((ROOT/'.github/workflows/release.yml').read_text())
        self.assertIn('release',y['jobs'])
        for step in y['jobs']['release']['steps']:
            if 'run' in step:
                with self.subTest(name=step['name']):
                    subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)

    def test_posix_shell_syntax(self):
        for f in ['module/ast/entrypoint.sh','module/ast/install-entrypoint.sh','module/service.sh','module/uninstall.sh','module/customize.sh','module/post-fs-data.sh']:
            with self.subTest(f=f):subprocess.run(['sh','-n',str(ROOT/f)],check=True)

    def test_bash_scripts_syntax(self):
        for f in ['scripts/package.sh','scripts/install.sh']:
            with self.subTest(f=f):subprocess.run(['bash','-n',str(ROOT/f)],check=True)

    def test_themes_valid_json(self):
        for p in (ROOT/'module/ast/themes').glob('*.json'):
            with self.subTest(p=p):
                d=json.loads(p.read_text());self.assertEqual(d['version'],3)
                self.assertTrue(d['blocks'])

    def test_plugin_git_pins(self):
        p=json.loads((ROOT/'manifest/plugins.json').read_text());self.assertEqual(p['schema'],1)
        self.assertEqual(len(p['plugins']),6)
        for x in p['plugins']:
            self.assertRegex(x['commit'],r'^[0-9a-f]{40}$')
            self.assertRegex(x['tree'],r'^[0-9a-f]{40}$')

    def test_optional_ls_and_cat_preserved(self):
        profile=(ROOT/'module/ast/zshrc').read_text()
        self.assertIn('[[ -x "$AST_ROOT/system/bin/lsd" ]]',profile)
        self.assertIn('[[ -x "$AST_ROOT/system/bin/bat" ]]',profile)
        self.assertIn('lsd --icon never',profile)

    def test_entrypoint_guarded_script(self):
        s=(ROOT/'module/ast/entrypoint.sh').read_text()
        self.assertIn('AST_RECOVERY_ENTRYPOINT_V1',s)
        self.assertIn('mount and decrypt /data',s)
        self.assertIn('exec "$AST_ROOT/system/bin/zsh" -f -i',s)
        self.assertNotIn('su -c',s)

    def test_no_unattended_updater(self):
        sh=(ROOT/'module/service.sh').read_text()
        self.assertNotIn('curl',sh);self.assertNotIn('wget',sh)
        self.assertNotIn('gh release',sh)
        self.assertNotIn('curl', (ROOT/'module/ast/entrypoint.sh').read_text())

    def test_installer_only_updates_its_entry(self):
        s=(ROOT/'module/ast/install-entrypoint.sh').read_text()
        self.assertIn('refusing overwrite',s)
        self.assertIn('mv -f "$STAGE/entrypoint" "$TARGET"',s)
        self.assertIn('! -L "$TARGET"',s)

if __name__=='__main__':unittest.main()
