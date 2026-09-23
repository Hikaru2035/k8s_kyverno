#!/usr/bin/env python3
"""Offline regression tests: real renderer, CLI, approval and byte-preserving package."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('approved', Path(__file__).with_name('approved-policies.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
ROOT = Path(__file__).resolve().parents[2]
ENVS = ('development', 'staging', 'production')


def fixture(root):
    f = root / 'k8s-security-framework'
    for directory in ('policies', 'profiles', 'scripts', 'tests/e2e_env'):
        shutil.copytree(ROOT / 'k8s-security-framework' / directory, f / directory)
    shutil.copytree(ROOT / 'jenkins/scripts', root / 'jenkins/scripts')
    shutil.copyfile(ROOT / 'versions.yaml', root / 'versions.yaml')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fixture(self.root)

    def plan(self, env):
        return a.build_plan(self.root, env, self.root / ('suites-' + env))

    def test_environment_adapter_exists(self):
        self.assertTrue(callable(getattr(a, 'build_plan', None)),
                        'An environment-aware case plan is required')

    def test_meta_preserves_resources_and_adapts_expected_evaluation(self):
        for env, good, bad in [('development', 'dev', 'staging'),
                               ('staging', 'staging', 'production'),
                               ('production', 'production', 'dev')]:
            cases = self.plan(env)['cases']
            for label, want in [(good, 'pass'), (bad, 'fail')]:
                row = next(c for c in cases if c['test_case'] == f'meta-003-{label}-baseline')
                self.assertEqual(row['expected_result'], want)
                self.assertEqual(row['status'], 'EXECUTED')
            self.assertEqual(sum(c['origin'] == 'canonical' for c in cases), 383)

    def test_audit_warn_vs_deny_admission_disposition(self):
        for env, want in [('development', 'allow-with-audit-and-warning'),
                          ('staging', 'deny'), ('production', 'deny')]:
            row = next(c for c in self.plan(env)['cases'] if c['test_case'] == 'img-001-negative-latest')
            self.assertEqual(row['expected_result'], 'fail')  # CLI evaluation, not admission denial
            self.assertEqual(row['admission'], want)

    def test_disabled_mutation_is_not_development_mutation_success(self):
        for env in ENVS:
            plan = self.plan(env)
            rows = [c for c in plan['cases'] if c['policy'] == 'KSP-POD-012']
            self.assertEqual(len(rows), 11)
            want = 'EXECUTED' if env == 'development' else 'NOT_APPLICABLE_TO_RENDERED_ADMISSION'
            self.assertEqual({c['status'] for c in rows}, {want})
            if env != 'development':
                self.assertEqual({c['reason'] for c in rows}, {'admission-mutation-disabled-for-environment'})
            config = next(c for c in plan['configuration'] if c['policy'] == 'KSP-POD-012' and c['assertion'] == 'admission-enabled')
            self.assertEqual(config['value'], env == 'development')

    def test_runtime_ownership_and_production_regression_are_separate(self):
        for env in ENVS:
            plan = self.plan(env)
            self.assertEqual(len(plan['runtime_e2e']), 18)
            self.assertTrue(all(r['owner'] == 'runtime-e2e' for r in plan['runtime_e2e']))
            self.assertFalse(any('scenario-' in c['test_case'] for c in plan['cases']))
            self.assertEqual(sum(c['origin'] == 'environment-regression' for c in plan['cases']),
                             3 if env == 'production' else 0)

    def test_case_omission_failure_substitution_and_unapproved_exemptions_rejected(self):
        plan = self.plan('staging')
        for change in ('omit', 'duplicate', 'failed', 'defer', 'na', 'reason', 'environment'):
            with self.subTest(change=change):
                actual = copy.deepcopy(plan)
                row = next(c for c in actual['cases'] if c['status'] == 'EXECUTED')
                if change == 'omit': actual['cases'].remove(row)
                elif change == 'duplicate': actual['cases'].append(copy.deepcopy(row))
                elif change == 'failed': row['status'] = 'FAILED'
                elif change == 'defer': row.update(status='DEFERRED', reason=a.DEFERRED_REASON)
                elif change == 'na': row.update(status='NOT_APPLICABLE_TO_RENDERED_ADMISSION', reason=a.DISABLED_REASON)
                elif change == 'reason':
                    next(c for c in actual['cases'] if c['status'] == 'NOT_APPLICABLE_TO_RENDERED_ADMISSION')['reason'] = 'ignore'
                else: row['environment'] = 'production'
                with self.assertRaises(ValueError): a.validate_approval(actual, plan)

    def test_wrong_rendered_configuration_and_environment_fail_closed(self):
        policy = next((self.root / 'k8s-security-framework/tests/e2e_env/staging/policies').rglob('KSP-POD-012-*.yaml'))
        doc = a.read_yaml(policy)
        doc['spec']['evaluation']['admission']['enabled'] = True
        a.write_yaml(policy, doc)
        with self.assertRaises(ValueError): self.plan('staging')
        for env in ('dev', 'prod', '../production', '', 'qa'):
            with self.assertRaises(ValueError): self.plan(env)

    def test_missing_and_substituted_policy_fail_closed(self):
        base = self.root / 'k8s-security-framework/tests/e2e_env/development/policies'
        path = next(base.rglob('*.yaml'))
        content = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError): self.plan('development')
        path.with_name('substituted.yaml').write_bytes(content)
        with self.assertRaises(ValueError): self.plan('development')

    def test_cli_missing_assertion_and_unexpected_exclusion_rejected(self):
        manifest = {'results': [{'policy': 'p', 'kind': 'Pod', 'resources': ['good'], 'result': 'pass'}]}
        for rows in ([], [{'POLICY': 'p', 'RESOURCE': 'v1/Pod/test/good', 'RESULT': 'Pass',
                           'REASON': 'Excluded', 'RULE': 'p'}]):
            with self.assertRaises(ValueError):
                a.check_output('\n' + json.dumps(rows), manifest, self.root)

    def test_invalid_environment_scripts_do_not_touch_evidence(self):
        evidence = self.root / 'artifacts/rendered-policy-test'
        evidence.mkdir(parents=True)
        marker = evidence / 'success.json'
        marker.write_text('existing')
        for script in ('check-policy.sh', 'rendered-policy-test.sh', 'package-approved-policies.sh'):
            run = subprocess.run(['bash', str(self.root / 'jenkins/scripts' / script), 'qa'],
                                 env=dict(os.environ, CI_PROJECT_DIR=str(self.root)), capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(marker.read_text(), 'existing')


@unittest.skipUnless(shutil.which('kyverno'), 'real Kyverno CLI required for integration')
class RealPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.roots = {}
        cls.commit_patch = patch.object(a, 'commit', return_value=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
        cls.commit_patch.start()
        cls.addClassCleanup(cls.commit_patch.stop)
        for env in ENVS:
            root = Path(cls.tmp.name) / env
            fixture(root)
            renderer = root / 'k8s-security-framework/scripts/render-policies.sh'
            original = renderer.with_name('render-policies-original.sh')
            renderer.rename(original)
            renderer.write_text('#!/usr/bin/env bash\nset -euo pipefail\nprintf \'%s\\n\' "$1" >> "$CI_PROJECT_DIR/render-calls.txt"\nexec bash "$(dirname "$0")/render-policies-original.sh" "$@"\n')
            run_env = dict(os.environ, CI_PROJECT_DIR=str(root), POLICY_ENVIRONMENT=env,
                           GIT_DIR=str(ROOT / '.git'), GIT_WORK_TREE=str(root), GIT_OPTIONAL_LOCKS='0')
            subprocess.run(['bash', str(root / 'jenkins/scripts/rendered-policy-test.sh')],
                           env=run_env, cwd=root, check=True)
            cls.roots[env] = root

    def setUp(self):
        self.tmp_case = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_case.cleanup)

    def clone(self, env):
        root = Path(self.tmp_case.name) / env
        shutil.copytree(self.roots[env], root)
        return root

    def test_all_environments_package_exact_tested_bundle(self):
        for env in ENVS:
            root = self.clone(env)
            a.package(root, env)
            output = root / f'artifacts/approved-policies-{env}'
            evidence = root / 'artifacts/rendered-policy-test'
            self.assertEqual((output / 'policy-inventory.txt').read_bytes(), (evidence / 'policy-inventory.txt').read_bytes())
            self.assertEqual(len(list((output / 'policies').rglob('*.yaml'))), 29)
            metadata = (output / 'metadata.txt').read_text()
            self.assertIn(f'environment={env}\n', metadata)
            self.assertIn('approval_mode=poc\n', metadata)
            self.assertTrue((output / 'test-coverage-summary.txt').is_file())
            self.assertEqual((root / 'render-calls.txt').read_text().splitlines(), [env])
            before = (evidence / 'policy-inventory.txt').read_text()
            self.assertEqual(a.inventory(output / 'policies', a.expected_policies(root)), before)
            coverage = json.loads((evidence / 'coverage.json').read_text())
            mutation = [c for c in coverage['cases'] if c['policy'] == 'KSP-POD-012']
            self.assertEqual(sum(c['status'] == 'EXECUTED' for c in mutation), 11 if env == 'development' else 0)

    def test_all_cross_environment_packages_rejected(self):
        for tested in ENVS:
            root = self.clone(tested)
            for requested in ENVS:
                if requested != tested:
                    with self.subTest(tested=tested, requested=requested), self.assertRaises(ValueError):
                        a.package(root, requested)

    def test_policy_byte_change_rejects_package(self):
        root = self.clone('development')
        path = next((root / 'k8s-security-framework/tests/e2e_env/development/policies').rglob('*.yaml'))
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(ValueError): a.package(root, 'development')

    def test_evidence_change_rejects_package(self):
        root = self.clone('staging')
        (root / 'artifacts/rendered-policy-test/coverage.json').write_text('{}')
        with self.assertRaises(ValueError): a.package(root, 'staging')

    def test_source_expectation_change_rejects_package(self):
        root = self.clone('production')
        path = next((root / 'k8s-security-framework/policies').rglob('kyverno-test.yaml'))
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(ValueError): a.package(root, 'production')

    def test_missing_policy_rejects_package(self):
        root = self.clone('development')
        next((root / 'k8s-security-framework/tests/e2e_env/development/policies').rglob('*.yaml')).unlink()
        with self.assertRaises(ValueError): a.package(root, 'development')

    def test_staged_copy_tampering_rejects_package(self):
        root = self.clone('production')
        real_copy = shutil.copytree
        def corrupt(source, destination, *args, **kwargs):
            result = real_copy(source, destination, *args, **kwargs)
            if Path(destination).name == 'policies':
                policy = next(Path(destination).rglob('*.yaml'))
                policy.write_bytes(policy.read_bytes() + b'\n')
            return result
        with patch.object(a.shutil, 'copytree', side_effect=corrupt), self.assertRaises(ValueError):
            a.package(root, 'production')
        self.assertFalse((root / 'artifacts/approved-policies-production').exists())

    def test_changed_configuration_and_inventory_receipt_rejected(self):
        root = self.clone('staging')
        receipt = root / 'artifacts/rendered-policy-test/render.json'
        data = json.loads(receipt.read_text())
        data['environment'] = 'development'
        receipt.write_text(json.dumps(data))
        with self.assertRaises(ValueError): a.package(root, 'staging')


if __name__ == '__main__':
    unittest.main()
