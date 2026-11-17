"""Exact-lock and single-event CI policy; no network or real device access."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ast_fetch_source_bound', ROOT/'scripts/fetch.py')
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)

COMMIT = '5ea67098a9bf2e32d6a85ef9775a19bf147b6285'
BLOB = '7ed130434d40c8f5c44eee85b192b3f0c6833e9d'


class LockedSourceTests(unittest.TestCase):
    def test_7zz_lock_is_commit_scoped_without_secret_live_network(self):
        lock=json.loads((ROOT/'manifest/lock.json').read_text())
        x=next(x for x in lock['tools'] if x['name']=='7zz')
        self.assertRegex(x['source_url'],r'/[0-9a-f]{40}/linux/arm64/7zzs$')
        self.assertEqual(x['version'],x['source_url'].split('/')[-4])
        self.assertNotIn('/main/',x['source_url'])
        self.assertEqual(x['sha256'],x['source_sha256'])
        self.assertTrue(x['static'])
        self.assertGreater(x['size'],0)

    def test_checksum_drift_refused_before_binary_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)
            def bad_download(url,path):
                path.write_bytes(b'not the locked executable')
            with patch.object(fetch,'stream_download',side_effect=bad_download):
                with self.assertRaisesRegex(RuntimeError,'source SHA-256 mismatch'):
                    fetch.cache_source('https://raw.githubusercontent.com/test/repo/exact/file',cache,'0'*64)
            self.assertEqual(list((cache/'downloads').glob('*')),[])


class ImmutableRepositoryResolverTests(unittest.TestCase):
    def mocked_api(self,url):
        if url.endswith('/repos/ollm/7zip-bin-full'):
            return {'default_branch':'main'}
        if url.endswith('/git/refs/heads/main'):
            return {'object':{'type':'commit','sha':COMMIT}}
        if url.endswith('/contents/linux/arm64/7zzs?ref='+COMMIT):
            return {'type':'file','sha':BLOB,'download_url':'https://evil.example/file'}
        raise AssertionError('Unexpected API call: '+url)

    def test_update_resolves_version_to_exact_commit_not_default_branch(self):
        with patch.object(fetch,'req_json',side_effect=self.mocked_api) as mocked:
            v,u,a=fetch.repo_file('ollm/7zip-bin-full',['linux/arm64/7zzs'])
        self.assertEqual(v,COMMIT)
        self.assertEqual(a,'7zzs')
        self.assertEqual(u,'https://raw.githubusercontent.com/ollm/7zip-bin-full/'+COMMIT+'/linux/arm64/7zzs')
        self.assertNotIn('evil',u)
        self.assertEqual(mocked.call_count,3)

    def test_refuse_noncommit_revision(self):
        def invalid(url):
            if url.endswith('/repos/ollm/7zip-bin-full'):return {'default_branch':'main'}
            return {'object':{'type':'commit','sha':'main'}}
        with patch.object(fetch,'req_json',side_effect=invalid):
            with self.assertRaisesRegex(RuntimeError,'pin an exact upstream commit'):
                fetch.repo_file('ollm/7zip-bin-full',['linux/arm64/7zzs'])

    def test_refuse_symlink_upstream_entry(self):
        def invalid(url):
            if url.endswith('/repos/ollm/7zip-bin-full'):return {'default_branch':'main'}
            if url.endswith('/git/refs/heads/main'):return {'object':{'type':'commit','sha':COMMIT}}
            return {'type':'symlink','sha':BLOB}
        with patch.object(fetch,'req_json',side_effect=invalid):
            with self.assertRaisesRegex(RuntimeError,'no ordinary file'):
                fetch.repo_file('ollm/7zip-bin-full',['linux/arm64/7zzs'])

    def test_refuse_paths_outside_expected_repository(self):
        with patch.object(fetch,'req_json',side_effect=self.mocked_api):
            with self.assertRaisesRegex(RuntimeError,'unsafe file path'):
                fetch.repo_file('ollm/7zip-bin-full',['../unsafe'])

    def test_no_silent_provider_version_update_inside_package(self):
        mk=(ROOT/'Makefile').read_text()
        wf=(ROOT/'.github/workflows/package.yml').read_text()
        self.assertIn('fetch: check',mk)
        self.assertIn('python3 scripts/fetch.py --mode locked',mk)
        self.assertIn('run: make fetch',wf)
        self.assertNotIn('run: make update\n      - name: Package',wf)


class SingleEventWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.wf=(ROOT/'.github/workflows/package.yml').read_text()

    def test_feature_push_is_not_eligible_for_second_workflow(self):
        pre=self.wf.split('\njobs:\n',1)[0]
        self.assertRegex(pre,r'(?m)^  pull_request:\s*$')
        self.assertRegex(pre,r'(?m)^  push:\n    branches:\n      - master\n')
        self.assertNotRegex(pre,r'(?m)^      - feature/')
        self.assertIn('paths:',pre)

    def test_new_head_cancels_only_superseded_same_pr_runs(self):
        self.assertIn('concurrency:',self.wf)
        self.assertIn('github.event.pull_request.number || github.ref',self.wf)
        self.assertIn('cancel-in-progress: true',self.wf)

    def test_manual_schedule_report_remains_separate_from_ci(self):
        self.assertIn('workflow_dispatch:',self.wf)
        self.assertIn('schedule:',self.wf)
        self.assertIn("if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'",self.wf)
        rel=(ROOT/'.github/workflows/release.yml').read_text()
        self.assertIn('workflow_dispatch:',rel)
        self.assertNotRegex(rel,r'(?m)^  push:|^  pull_request:')

if __name__=='__main__':unittest.main()
