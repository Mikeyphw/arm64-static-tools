"""Test hosted CI deduplication and the committed native required-CI contract."""
from __future__ import annotations
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'config/delivery-required-ci.json'
WF=ROOT/'.github/workflows/package.yml'

class NativePolicyTests(unittest.TestCase):
    def test_exact_policy_identity_and_workflow_id(self):
        p=json.loads(POLICY.read_text())
        self.assertEqual(set(p),{'schema_version','repository','base_branch','event','release_qualification','required_workflows'})
        self.assertEqual(p['schema_version'],1)
        self.assertEqual(p['repository'],'Mikeyphw/arm64-static-tools')
        self.assertEqual(p['base_branch'],'feature/ast-recovery-ci-qualification-20261117')
        self.assertEqual(p['event'],'pull_request')
        self.assertEqual(p['release_qualification'],'separate')
        self.assertEqual(p['required_workflows'],[{'name':'Package ARM64 module','workflow_id':420937101}])
    def test_policy_names_live_workflow_and_no_skip_paths_for_pr(self):
        data=WF.read_text()
        p=json.loads(POLICY.read_text())
        self.assertIn('name: '+p['required_workflows'][0]['name']+'\n',data)
        self.assertRegex(data,r'(?m)^  pull_request:\s*$')
        self.assertNotRegex(data,r'(?ms)^  pull_request:\n +(?:paths|branches|types):')
    def test_single_make_graph_contains_one_suite(self):
        p=subprocess.run(['make','-n','check','package'],cwd=ROOT,
                          capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(p.stdout.count('python3 -m unittest discover'),1)
        self.assertEqual(p.stdout.count('python3 scripts/verify_manifest.py'),1)
        self.assertEqual(p.stdout.count('python3 scripts/check_repo_purity.py'),1)
        self.assertEqual(p.stdout.count('bash scripts/package.sh'),1)
        self.assertNotIn('scripts/fetch.py --mode update',p.stdout)
    def test_locked_fetch_happens_once_in_packaging_recipe(self):
        sh=(ROOT/'scripts/package.sh').read_text()
        self.assertEqual(len(re.findall(r'python3 scripts/fetch\.py\s*\\\n\s*--mode locked',sh)),1)
        self.assertIn('--provenance',sh)
        self.assertIn('--export-dir',sh)
        self.assertIn('scripts/verify_module_zip.py',sh)
    def test_pr_runs_one_package_step_and_push_only_master(self):
        data=WF.read_text()
        self.assertEqual(data.count('run: make check package'),1)
        self.assertNotIn('run: make check\n',data)
        self.assertNotIn('run: make fetch\n',data)
        self.assertNotIn('run: make package\n',data)
        self.assertRegex(data,r'(?m)^  push:\n    branches:\n      - master\n')
        self.assertIn("      - 'config/**'",data)
        self.assertIn('actions/upload-artifact@v4',data)
        self.assertIn('if-no-files-found: error',data)
    def test_policy_cannot_claim_release_or_current_old_session(self):
        doc=(ROOT/'docs/CI_NATIVE_QUALIFICATION.md').read_text()
        self.assertIn('old session',doc)
        self.assertIn('REQUIRED_CHECKS_PASSED',doc)
        self.assertIn('BRANCH_RULES_UNVERIFIED',doc)
        self.assertIn('release',doc)

if __name__=='__main__': unittest.main()
