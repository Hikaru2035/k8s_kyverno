#!/usr/bin/env python3
"""Environment-aware offline rendered admission evidence and exact-byte packaging."""
import argparse
import ast
from collections import Counter
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

DEFERRED_POLICY = 'KSP-IMG-004'
DEFERRED_REASON = 'external-registry-signature-verification-deferred-for-poc'
DISABLED_REASON = 'admission-mutation-disabled-for-environment'
NA = 'NOT_APPLICABLE_TO_RENDERED_ADMISSION'
FRAMEWORK = 'k8s-security-framework'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_yaml(path):
    return yaml.safe_load(path.read_text())


def write_yaml(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def commit(root):
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def environments(root):
    # Read the renderer's data, without invoking it a second time.
    tree = ast.parse((root / FRAMEWORK / 'scripts/render-policies.py').read_text())
    entries = [ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ENV' for t in node.targets)]
    require(len(entries) == 1, 'Renderer environment mapping missing or ambiguous')
    return entries[0]


def environment(root, env):
    mapping = environments(root)
    require(env in mapping and env in ('development', 'staging', 'production'), f'Invalid environment: {env}')
    return mapping[env]


def bundle_path(root, env):
    environment(root, env)
    return root / FRAMEWORK / 'tests/e2e_env' / env / 'policies'


def expected_policies(root):
    framework = root / FRAMEWORK
    profiles = {}
    for group in ('baseline', 'standard', 'restricted'):
        ids = (framework / 'profiles' / group / 'policy-ids.txt').read_text().split()
        require(len(ids) == len(set(ids)), f'Duplicate IDs in {group}')
        profiles[group] = set(ids)
    require(profiles['baseline'] <= profiles['standard'] <= profiles['restricted'], 'Profiles must be cumulative')
    sources = {}
    for source in sorted((framework / 'policies').glob('*/KSP-*/KSP-*.yaml')):
        require(source.parent.name not in sources, 'Duplicate source policy')
        sources[source.parent.name] = source
    require(set(sources) == profiles['restricted'], 'Source/profile inventory mismatch')
    result = {}
    for policy_id, source in sorted(sources.items()):
        group = next(g for g in profiles if policy_id in profiles[g])
        if policy_id == 'KSP-META-003':
            group = 'common'
        result[f'{group}/{source.name}'] = source
    return dict(sorted(result.items()))


def inventory(directory, expected):
    require(directory.is_dir(), f'Missing bundle: {directory}')
    files = sorted(p for p in directory.rglob('*') if p.is_file())
    require(not directory.is_symlink() and not any(p.is_symlink() for p in directory.rglob('*')), 'Symlink in policy bundle')
    require([p.relative_to(directory).as_posix() for p in files] == sorted(expected), 'Missing or unexpected policy files')
    return ''.join(f'{sha(p.read_bytes())}  {p.relative_to(directory).as_posix()}\n' for p in files)


def evidence_digest(directory):
    require(not any(p.is_symlink() for p in directory.rglob('*')), 'Symlink in evidence')
    entries = ''.join(f'{sha(p.read_bytes())}  {p.relative_to(directory).as_posix()}\n'
                      for p in sorted(directory.rglob('*')) if p.is_file() and p.name != 'success.json')
    return sha(entries.encode())


def input_digest(root, env):
    """Bind dirty working-tree inputs too, rather than trusting git commit alone."""
    framework = root / FRAMEWORK
    paths = [root / 'versions.yaml']
    for directory in (framework / 'policies', framework / 'profiles', framework / 'scripts', root / 'jenkins/scripts'):
        paths.extend(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    base = framework / 'tests/e2e_env' / env
    paths.append(base / 'platform-namespaces.yaml')
    paths.extend(p for p in (base / 'tests').rglob('*') if p.is_file())
    return sha(''.join(f'{sha(p.read_bytes())}  {p.relative_to(root)}\n' for p in sorted(paths)).encode())


def verify_configuration(root, source, policy, env):
    """Assert the renderer's allowed transformations without rendering/writing YAML."""
    label, mode_key = environment(root, env)
    original, rendered = read_yaml(source), read_yaml(policy)
    pid, group = source.parent.name, policy.parent.name
    annotations = original['metadata']['annotations']
    mode = annotations['policies.ksp.io/' + mode_key]
    expected_metadata = copy.deepcopy(original['metadata'])
    expected_metadata['annotations'].update({
        'policies.ksp.io/runtime-environment': env,
        'policies.ksp.io/rendered-from': str(source.relative_to(root / FRAMEWORK))})
    require(rendered['metadata'] == expected_metadata, f'{pid}: rendered environment/identity/metadata mismatch')
    require(rendered['kind'] == original['kind'] and rendered['apiVersion'] == original['apiVersion'], f'{pid}: policy type mismatch')
    config = []

    def assertion(name, actual, expected):
        require(actual == expected, f'{pid}: {name}: {actual!r} != {expected!r}')
        config.append(dict(policy=pid, environment=env, assertion=name, value=actual, status='EXECUTED'))

    assertion('runtime-environment', rendered['metadata']['annotations']['policies.ksp.io/runtime-environment'], env)
    # Compare all untouched policy content after removing only verified transformations.
    before, after = copy.deepcopy(original['spec']), copy.deepcopy(rendered['spec'])
    kind = original['kind']
    if kind in ('ValidatingPolicy', 'ImageValidatingPolicy'):
        require(mode in ('Enforce', 'Audit/Enforce', 'Audit'), f'{pid}: unsupported mode {mode}')
        actions = ['Deny'] if mode in ('Enforce', 'Audit/Enforce') else ['Audit', 'Warn']
        assertion('validation-actions', after['validationActions'], actions)
        before.pop('validationActions', None); after.pop('validationActions')
    if kind == 'MutatingPolicy':
        require(mode in ('Mutate', 'Audit', 'Disabled'), f'{pid}: unsupported mutation mode')
        expected = False if mode in ('Audit', 'Disabled') else before.get('evaluation', {}).get('admission', {}).get('enabled', True)
        assertion('admission-enabled', after.get('evaluation', {}).get('admission', {}).get('enabled', True), expected)
        if not expected:
            # Disabled admission is allowed only for the explicitly contracted policy.
            require(pid == 'KSP-POD-012', f'{pid}: disabled-admission classification is not authorized')
            before.setdefault('evaluation', {}).setdefault('admission', {})['enabled'] = False
    platforms = read_yaml(root / FRAMEWORK / 'tests/e2e_env' / env / 'platform-namespaces.yaml')['platformNamespaces']
    namespace_policy = any('namespaces' in r.get('resources', []) for r in before.get('matchConstraints', {}).get('resourceRules', []))
    if not namespace_policy and group in ('standard', 'restricted'):
        selector = copy.deepcopy(before['matchConstraints'].get('namespaceSelector', {}))
        selector.setdefault('matchExpressions', []).append(dict(key='ksp.io/profile', operator='In',
            values=['standard', 'restricted'] if group == 'standard' else ['restricted']))
        assertion('profile-selector', after['matchConstraints']['namespaceSelector'], selector)
        before['matchConstraints']['namespaceSelector'] = selector
    if pid == 'KSP-META-003':
        expression = f"object.metadata.?labels['ksp.io/environment'].orValue('') == '{label}'"
        assertion('environment-predicate', after['validations'][0]['expression'], expression)
        before['validations'][0] = dict(expression=expression, message=f'Set ksp.io/environment to {label} for this {env} cluster.')
        assertion('platform-exemptions', after['matchConstraints']['excludeResourceRules'][0]['resourceNames'], platforms)
        before['matchConstraints']['excludeResourceRules'][0]['resourceNames'] = platforms
    else:
        profile = 'true'
        if namespace_policy and group == 'standard':
            profile = "object.metadata.?labels['ksp.io/profile'].orValue('') in ['standard', 'restricted']"
        elif namespace_policy and group == 'restricted':
            profile = "object.metadata.?labels['ksp.io/profile'].orValue('') == 'restricted'"
        target = 'object.metadata.name' if namespace_policy else 'request.namespace'
        condition = dict(name='ksp-runtime-profile-and-platform-scope', expression=f'({profile}) && (!({target} in {platforms!r}))')
        conditions = before.get('matchConditions', []) + [condition]
        assertion('profile-platform-condition', after['matchConditions'], conditions)
        before['matchConditions'] = conditions
    assertion('remaining-policy-content', after, before)
    return config


def admission_expectation(policy, result):
    if result == 'skip':
        return 'not-selected-or-excepted'
    kind, spec = policy['kind'], policy['spec']
    if kind in ('ValidatingPolicy', 'ImageValidatingPolicy'):
        if result == 'pass':
            return 'allow'
        actions = spec['validationActions']
        if 'Deny' in actions:
            return 'deny'
        require(actions == ['Audit', 'Warn'], 'Unsupported admission actions')
        return 'allow-with-audit-and-warning'
    if kind == 'MutatingPolicy':
        return 'mutate' if spec.get('evaluation', {}).get('admission', {}).get('enabled', True) else 'mutation-disabled'
    require(kind == 'GeneratingPolicy', f'Unsupported policy kind {kind}')
    return 'offline-generation-evaluation'


def expected_cases(manifest):
    cases = {}
    for result in manifest['results']:
        for resource in result['resources']:
            key = (result['policy'], result['kind'], resource)
            require(key not in cases, f'Duplicate expected case: {key}')
            require(result['result'] in ('pass', 'fail', 'skip'), f'Unsupported test expectation: {result}')
            cases[key] = result['result']
    return cases


def prepare_suite(root, source, policy_path, env, destination, origin='canonical', existing=None):
    pid = source.parent.name
    suite_key = f'{pid}/{origin}'
    shutil.copytree(existing or source.parent / 'tests', destination)
    manifest = read_yaml(destination / 'kyverno-test.yaml')
    if origin == 'canonical':
        require(manifest['policies'] == [f'../{source.name}'], f'Unexpected canonical test mapping: {pid}')
    else:
        require(len(manifest['policies']) == 1 and (existing / manifest['policies'][0]).resolve() == policy_path.resolve(),
                f'Unexpected environment regression mapping: {pid}')
    manifest['policies'] = [os.path.relpath(policy_path, destination)]
    policy = read_yaml(policy_path)
    group = policy_path.parent.name
    profile = group if group in ('standard', 'restricted') else 'baseline'
    values = (read_yaml(destination / manifest['variables']) if 'variables' in manifest else
              dict(apiVersion='cli.kyverno.io/v1alpha1', kind='Values', metadata={'name': f'rendered-{env}'}))
    namespaces = {n['name']: n.get('labels', {}) for n in values.get('namespaceSelector', [])}
    resources, documents = {}, {}
    for filename in manifest['resources']:
        path = destination / filename
        docs = list(yaml.safe_load_all(path.read_text()))
        for resource in docs:
            metadata = resource['metadata']
            # Explicit existing source fixture typo: keep canonical assertion identity.
            if pid == 'KSP-POD-008' and metadata['name'] == 'pod-008-negative-missiing-drop':
                metadata['name'] = 'pod-008-negative-missing-drop'
            if resource['kind'] == 'Namespace' and pid != 'KSP-META-003':
                metadata.setdefault('labels', {})['ksp.io/profile'] = profile
            elif resource['kind'] != 'Namespace':
                namespaces.setdefault(metadata.get('namespace', 'default'), {})
            key = (resource['kind'], metadata['name'])
            require(key not in resources, f'Duplicate fixture: {key}')
            resources[key] = resource
        documents[filename] = docs
    for labels in namespaces.values():
        labels['ksp.io/profile'] = profile
    values['namespaceSelector'] = [dict(name=n, labels=labels) for n, labels in sorted(namespaces.items())]
    write_yaml(destination / 'rendered-values.yaml', values)
    manifest['variables'] = 'rendered-values.yaml'
    expected_cases(manifest)
    cases, results, executed_resources = [], [], set()
    disabled = policy['kind'] == 'MutatingPolicy' and policy['spec'].get('evaluation', {}).get('admission', {}).get('enabled') is False
    platforms = read_yaml(root / FRAMEWORK / 'tests/e2e_env' / env / 'platform-namespaces.yaml')['platformNamespaces']
    for result in manifest['results']:
        for name in result['resources']:
            key = (result['kind'], name)
            require(key in resources, f'Test references missing fixture: {pid}/{name}')
            resource = resources[key]
            adapted = copy.deepcopy(result)
            adapted['resources'] = [name]
            if pid == 'KSP-META-003':
                # Preserve every original fixture, including other-environment negative probes.
                labels = resource['metadata'].get('labels', {})
                adapted['result'] = ('skip' if name in platforms else
                    'pass' if labels.get('ksp.io/environment') == environment(root, env)[0]
                    and labels.get('ksp.io/profile') in ('baseline', 'standard', 'restricted') else 'fail')
            record = dict(id=f'{suite_key}/{result["kind"]}/{name}', policy=pid, test_case=name,
                          environment=env, origin=origin, suite=suite_key, canonical_result=result['result'],
                          expected_result=adapted['result'], admission=admission_expectation(policy, adapted['result']), status='EXECUTED')
            if disabled:
                require(pid == 'KSP-POD-012', 'Unauthorized disabled admission exemption')
                record.update(status=NA, reason=DISABLED_REASON, admission='mutation-disabled')
            elif pid == DEFERRED_POLICY and adapted['result'] != 'skip':
                require(policy['kind'] == 'ImageValidatingPolicy', 'Signature deferral requires image validation policy')
                patterns = [p['glob'] for p in policy['spec']['matchImageReferences']]
                images = [c['image'] for field in ('containers', 'initContainers', 'ephemeralContainers')
                          for c in resource.get('spec', {}).get(field, [])]
                if any(fnmatch.fnmatchcase(image, pattern) for image in images for pattern in patterns):
                    require('harbor-registry-credentials' in policy['spec']['credentials']['secrets']
                            and policy['spec'].get('attestors'), 'Unauthorized signature deferral')
                    record.update(status='DEFERRED', reason=DEFERRED_REASON)
            if record['status'] == 'EXECUTED':
                results.append(adapted)
                executed_resources.add(key)
            cases.append(record)
    # Remove resources belonging solely to deferred/disabled assertions before CLI execution.
    manifest['results'] = results
    manifest['resources'] = []
    for filename, docs in documents.items():
        selected = [d for d in docs if (d['kind'], d['metadata']['name']) in executed_resources]
        (destination / filename).write_text(yaml.safe_dump_all(selected, sort_keys=False))
        if selected:
            manifest['resources'].append(filename)
    write_yaml(destination / 'kyverno-test.yaml', manifest)
    return cases


def build_plan(root, env, suites):
    environment(root, env)
    expected = expected_policies(root)
    bundle = bundle_path(root, env)
    inventory(bundle, expected)
    require(not suites.exists(), 'Suite destination must be fresh')
    suites.mkdir(parents=True)
    plan = dict(environment=env, policies=[], cases=[], configuration=[], runtime_e2e=[])
    for relative, source in expected.items():
        pid, policy = source.parent.name, bundle / relative
        plan['policies'].append(dict(policy=pid, path=relative))
        plan['configuration'].extend(verify_configuration(root, source, policy, env))
        plan['cases'].extend(prepare_suite(root, source, policy, env, suites / pid / 'canonical'))
        existing = root / FRAMEWORK / 'tests/e2e_env' / env / 'tests/rendered' / pid
        if (existing / 'kyverno-test.yaml').exists():
            plan['cases'].extend(prepare_suite(root, source, policy, env, suites / pid / 'environment-regression',
                                               'environment-regression', existing))
    regression_root = root / FRAMEWORK / 'tests/e2e_env' / env / 'tests/rendered'
    discovered = {p.parent.name for p in regression_root.rglob('kyverno-test.yaml')}
    included = {c['policy'] for c in plan['cases'] if c['origin'] == 'environment-regression'}
    require(discovered == included, 'Unaccounted environment regression suites')
    for path in sorted((root / FRAMEWORK / 'tests/e2e_env' / env / 'tests').glob('scenario-*.yaml')):
        plan['runtime_e2e'].append(dict(scenario=str(path.relative_to(root)), environment=env,
                                        owner='runtime-e2e', rendered_ci_execution='no'))
    return plan


def validate_approval(actual, expected):
    require(actual == expected, 'Coverage differs from authorized environment case plan (failure, omission, or unauthorized classification)')
    ids = [c['id'] for c in actual['cases']]
    require(len(ids) == len(set(ids)), 'Duplicate case identity')
    require({p['policy'] for p in actual['policies']} == {c['policy'] for c in actual['cases']}, 'Unaccounted policy')
    for case in actual['cases']:
        require(case['environment'] == actual['environment'], 'Case environment mismatch')
        if case['status'] == NA:
            require(case['policy'] == 'KSP-POD-012' and case.get('reason') == DISABLED_REASON,
                    'Unauthorized non-applicable case')
        elif case['status'] == 'DEFERRED':
            require(case['policy'] == DEFERRED_POLICY and case.get('reason') == DEFERRED_REASON, 'Unauthorized deferral')
        else:
            require(case['status'] == 'EXECUTED' and 'reason' not in case, 'Applicable case did not execute successfully')


def coverage_summary(coverage):
    counts = Counter(c['status'] for c in coverage['cases'])
    return dict(expected_policies=len(coverage['policies']),
                accounted_policies=len({c['policy'] for c in coverage['cases']}),
                canonical_cases=sum(c['origin'] == 'canonical' for c in coverage['cases']),
                environment_regression_cases=sum(c['origin'] == 'environment-regression' for c in coverage['cases']),
                executed=counts['EXECUTED'], not_applicable=counts[NA], deferred=counts['DEFERRED'], failed=counts['FAILED'],
                configuration_assertions=len(coverage['configuration']), runtime_e2e_owned_by_delivery=len(coverage['runtime_e2e']))


def summary_text(env, summary):
    return f'environment={env}\n' + ''.join(f'{key}={value}\n' for key, value in summary.items())


def record_render(root, env):
    expected = expected_policies(root)
    bundle = bundle_path(root, env)
    for relative, source in expected.items():
        verify_configuration(root, source, bundle / relative, env)
    evidence = root / 'artifacts/rendered-policy-test'
    evidence.mkdir(parents=True, exist_ok=True)
    require(not (evidence / 'render.json').exists(), 'Render receipt already exists; use a fresh run')
    write_json(evidence / 'render.json', dict(environment=env, git_commit=commit(root),
        inventory_sha256=sha(inventory(bundle, expected).encode()), inputs_sha256=input_digest(root, env)))


def verify_receipt(root, env):
    environment(root, env)
    evidence = root / 'artifacts/rendered-policy-test'
    receipt = json.loads((evidence / 'render.json').read_text())
    require(receipt['environment'] == env, 'Rendered environment differs from selected environment')
    require(receipt['git_commit'] == commit(root), 'Rendered commit differs from checkout')
    require(receipt['inputs_sha256'] == input_digest(root, env), 'Framework/test inputs changed since rendering')
    require(receipt['inventory_sha256'] == sha(inventory(bundle_path(root, env), expected_policies(root)).encode()),
            'Rendered bytes differ from render receipt')
    return receipt
def check_output(output, manifest, suite):
    # Kyverno 1.18 emits progress before JSON and a text summary after it.
    start = output.index('\n[')
    rows, _ = json.JSONDecoder().raw_decode(output[start + 1:])
    expected_cases(manifest)
    expected = Counter()
    for result in manifest['results']:
        for name in result['resources']:
            if 'generatedResource' in result:
                # Generate assertions report each expected output, not the trigger Namespace.
                for generated in yaml.safe_load_all((suite / result['generatedResource']).read_text()):
                    expected[(result['policy'], '', generated['metadata']['name'], 'active')] += 1
            else:
                mode = 'skip' if result['result'] == 'skip' else 'active'
                expected[(result['policy'], result['kind'], name, mode)] += 1
    actual = Counter()
    for row in rows:
        parts = row['RESOURCE'].split('/')
        kind = parts[-3] if len(parts) >= 3 else ''
        key = (row['POLICY'], kind, parts[-1])
        mode = 'skip' if (*key, 'skip') in expected else 'active'
        actual[(*key, mode)] += 1
        require(row['RESULT'] == 'Pass', f'Failed assertion: {row}')
        if mode == 'active':
            require(row['REASON'] == 'Ok' and row['RULE'] != 'exception',
                    f'Unexpected skipped/error case: {row}')
    require(actual == expected, f'Missing or unexpected assertions: {expected - actual}; {actual - expected}')



def test(root, env):
    environment(root, env)
    evidence = root / 'artifacts/rendered-policy-test'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'success.json').unlink(missing_ok=True)
    receipt = verify_receipt(root, env)
    expected = expected_policies(root)
    before = inventory(bundle_path(root, env), expected)
    (evidence / 'policy-inventory.txt').write_text(before)
    suites = evidence / 'suites'
    if suites.exists():
        shutil.rmtree(suites)
    plan = build_plan(root, env, suites)
    write_json(evidence / 'case-plan.json', plan)
    coverage = copy.deepcopy(plan)
    version = subprocess.check_output(['kyverno', 'version'], text=True)
    (evidence / 'kyverno-version.txt').write_text(version)
    pinned = read_yaml(root / 'versions.yaml')['policy_engine']['kyverno_cli']['version']
    require(f'Version: {pinned}\n' in version, 'Kyverno CLI differs from repository pin')
    for key in sorted({c['suite'] for c in coverage['cases']}):
        cases = [c for c in coverage['cases'] if c['suite'] == key and c['status'] == 'EXECUTED']
        if not cases:
            continue
        suite = suites / key
        manifest = read_yaml(suite / 'kyverno-test.yaml')
        output = ''
        try:
            run = subprocess.run(['kyverno', 'test', str(suite), '--remove-color', '--require-tests',
                                  '--detailed-results', '--output-format', 'json'], cwd=root, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            output = run.stdout
            require(run.returncode == 0, f'Kyverno exit status {run.returncode}')
            check_output(output, manifest, suite)
        except (ValueError, KeyError, IndexError, OSError, subprocess.TimeoutExpired) as error:
            output += f'\nAssertion verification failed: {error}\n'
            for case in cases:
                case.update(status='FAILED', reason='cli-suite-not-verified')
        (suite / 'output.txt').write_text(output)
        print(f'{env} {key}: {dict(Counter(c["status"] for c in coverage["cases"] if c["suite"] == key))}', flush=True)
    write_json(evidence / 'coverage.json', coverage)
    summary = coverage_summary(coverage)
    write_json(evidence / 'summary.json', summary)
    (evidence / 'test-coverage-summary.txt').write_text(summary_text(env, summary))
    (evidence / 'runtime-e2e-inventory.txt').write_text(''.join(
        f'{r["scenario"]}\tenvironment={env}\towner=runtime-e2e\trendered-ci-execution=no\n' for r in plan['runtime_e2e']))
    print(summary_text(env, summary), flush=True)
    require(inventory(bundle_path(root, env), expected) == before, 'Policy bytes changed during testing')
    verify_receipt(root, env)
    validate_approval(coverage, plan)
    write_json(evidence / 'success.json', dict(environment=env, git_commit=commit(root),
        inventory_sha256=sha(before.encode()), inputs_sha256=receipt['inputs_sha256'], summary=summary,
        test_evidence_sha256=evidence_digest(evidence)))


def package(root, env):
    environment(root, env)
    evidence = root / 'artifacts/rendered-policy-test'
    success = json.loads((evidence / 'success.json').read_text())
    require(success['environment'] == env, 'Test environment differs from package environment')
    receipt = verify_receipt(root, env)
    require(success['git_commit'] == commit(root) and success['inputs_sha256'] == receipt['inputs_sha256'], 'Tested inputs differ')
    require(evidence_digest(evidence) == success['test_evidence_sha256'], 'Test evidence is missing or modified')
    expected = expected_policies(root)
    tested = (evidence / 'policy-inventory.txt').read_text()
    require(sha(tested.encode()) == success['inventory_sha256'] == receipt['inventory_sha256'], 'Tested inventory was modified')
    bundle = bundle_path(root, env)
    require(inventory(bundle, expected) == tested, 'Rendered files differ from tested files')
    coverage = json.loads((evidence / 'coverage.json').read_text())
    # Reconstruct the case contract only; never call the renderer or mutate policy YAML.
    with tempfile.TemporaryDirectory() as temp:
        plan = build_plan(root, env, Path(temp) / 'suites')
    validate_approval(coverage, plan)
    summary = coverage_summary(coverage)
    require(success['summary'] == json.loads((evidence / 'summary.json').read_text()) == summary, 'Coverage summary mismatch')
    require(json.loads((evidence / 'case-plan.json').read_text()) == plan, 'Case plan mismatch')
    output = root / f'artifacts/approved-policies-{env}'
    require(not output.exists(), 'Approved output already exists; use a fresh CI workspace')
    version = read_yaml(root / 'versions.yaml')['framework']['version']
    require(isinstance(version, str) and version and '\n' not in version, 'Invalid framework version')
    with tempfile.TemporaryDirectory(prefix='.approved-', dir=root / 'artifacts') as temporary:
        staged = Path(temporary) / output.name
        shutil.copytree(bundle, staged / 'policies')
        require(inventory(staged / 'policies', expected) == tested, 'Packaged inventory differs')
        (staged / 'policy-inventory.txt').write_text(tested)
        (staged / 'test-coverage-summary.txt').write_text(summary_text(env, summary))
        metadata = dict(git_commit=success['git_commit'], environment=env, framework_version=version,
                        policy_count=len(expected), policy_inventory_sha256=success['inventory_sha256'],
                        test_evidence_sha256=success['test_evidence_sha256'], approval_mode='poc', **summary)
        if summary['deferred']:
            metadata.update(deferred_policy=DEFERRED_POLICY, deferred_reason=DEFERRED_REASON)
        if summary['not_applicable']:
            metadata['not_applicable_reason'] = DISABLED_REASON
        (staged / 'metadata.txt').write_text(''.join(f'{k}={v}\n' for k, v in metadata.items()))
        # Last check also protects against a changing source during the copy.
        require(inventory(bundle, expected) == tested, 'Bundle changed while packaging')
        staged.rename(output)
    print(f'{env}: rendered == tested == packaged; tested SHA-256 inventory == packaged SHA-256 inventory ({success["inventory_sha256"]})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['record-render', 'test', 'package'])
    parser.add_argument('environment', choices=['development', 'staging', 'production'])
    args = parser.parse_args()
    project = Path(os.environ.get('CI_PROJECT_DIR', Path.cwd())).resolve()
    try:
        {'record-render': record_render, 'test': test, 'package': package}[args.command](project, args.environment)
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error))
