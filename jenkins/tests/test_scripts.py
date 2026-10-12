"""Offline behavioral checks; command doubles never claim a real Kyverno pass."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Scripts(unittest.TestCase):
    def test_cli_aggregates_failure_and_runs_every_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            policy_root = work / 'k8s-security-framework/policies'
            for i in range(29):
                suite = policy_root / f'pod/KSP-POD-{i:03}/tests'
                suite.mkdir(parents=True)
                (suite / 'kyverno-test.yaml').write_text('kind: Test\n')
            command = work / 'kyverno'
            command.write_text('''#!/bin/bash
if [[ $1 == version ]]; then echo 1.18.2; exit 0; fi
echo "$2" >> "$CALLS"
if [[ "$*" == *junit* ]]; then
  printf '<?xml version="1.0"?>\n<testsuites><testsuite name="fixture" tests="1" failures="0"><testcase name="fixture"/></testsuite>\n</testsuites>\n'
fi
[[ "$2" != *KSP-POD-000* ]]
''')
            command.chmod(0o755)
            env = dict(os.environ, PATH=f'{work}:{os.environ["PATH"]}',
                       CI_PROJECT_DIR=str(work), CALLS=str(work / 'calls'))
            run = subprocess.run(['bash', str(ROOT / 'jenkins/scripts/cli-unit.sh')],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertTrue((work / 'calls').exists(), run.stderr)
            self.assertEqual(len((work / 'calls').read_text().splitlines()), 58)
            summary = (work / 'artifacts/cli-unit/summary.txt').read_text()
            self.assertIn('TOTAL=29', summary)
            self.assertIn('FAIL=1', summary)
            self.assertIn('PASS=28', summary)
            (policy_root / 'pod/KSP-POD-028/tests/kyverno-test.yaml').unlink()
            (work / 'calls').unlink()
            run = subprocess.run(['bash', str(ROOT / 'jenkins/scripts/cli-unit.sh')],
                                 env=env, capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((work / 'calls').exists())

    def test_render_requires_digest_and_preserves_source(self):
        source = ROOT / 'gitops/applications/demo-app/deployment.yaml'
        self.assertTrue(source.exists(), 'demo source manifest missing')
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            for ref in ['harbor-public:30003/ksp-test/demo-app:latest',
                        'harbor-public:30003/ksp-test/demo-app@sha256:bad']:
                run = subprocess.run(['python3', str(ROOT / 'jenkins/scripts/manifests.py'),
                                      'delivery', ref, tmp], capture_output=True)
                self.assertNotEqual(run.returncode, 0)
            ref = 'harbor-public:30003/ksp-test/demo-app@sha256:' + 'a' * 64
            run = subprocess.run(['python3', str(ROOT / 'jenkins/scripts/manifests.py'),
                                  'delivery', ref, tmp], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(ref, (Path(tmp) / 'deployment.yaml').read_text())
            self.assertTrue((Path(tmp) / 'pod.yaml').exists())
        self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

class LivePolicies(unittest.TestCase):
    def test_missing_policy_and_scope_drift_are_rejected(self):
        import importlib.util
        import copy
        import yaml
        spec = importlib.util.spec_from_file_location('live', ROOT / 'jenkins/scripts/live-policies.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        paths = sorted((ROOT / 'k8s-security-framework/tests/e2e_env/production/policies').glob('*/*.yaml'))
        objects = [yaml.safe_load(p.read_text()) for p in paths]
        for obj in objects:
            obj['status'] = {'conditions': [{'type': 'Ready', 'status': 'True'}]}
        module.check({'items': objects}, paths)
        with self.assertRaisesRegex(ValueError, 'Missing policy'):
            module.check({'items': objects[1:]}, paths)
        changed = copy.deepcopy(objects)
        policy = next(o for o in changed if o['kind'] == 'ValidatingPolicy')
        policy['spec']['matchConstraints']['excludeResourceRules'] = [{'resources': ['pods']}]
        with self.assertRaisesRegex(ValueError, 'Policy drift'):
            module.check({'items': changed}, paths)
        changed = copy.deepcopy(objects)
        changed[0]['spec']['evaluation'] = {'admission': {'enabled': False}}
        with self.assertRaises(ValueError):
            module.check({'items': changed}, paths)
