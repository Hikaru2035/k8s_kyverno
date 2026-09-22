#!/usr/bin/env python3
"""Render evidence without changing source manifests or policy semantics."""
import copy
import re
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK = ROOT / 'k8s-security-framework'


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False))


def pod_for(workload, namespace):
    template = workload['spec']['template']
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': workload['metadata']['name'] + '-preflight',
                         'namespace': namespace, **copy.deepcopy(template['metadata'])},
            'spec': copy.deepcopy(template['spec'])}


def delivery(reference, destination):
    if not re.fullmatch(r'harbor-public:30003/ksp-test/demo-app@sha256:[0-9a-f]{64}', reference):
        raise SystemExit('Expected the immutable Harbor demo-app SHA256 reference')
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / 'demo-app/k8s').glob('*.yaml'):
        resource = yaml.safe_load(path.read_text())
        if resource['kind'] == 'Deployment':
            resource['spec']['template']['spec']['containers'][0]['image'] = reference
            write(out / 'pod.yaml', pod_for(resource, 'ksp-demo'))
        write(out / path.name, resource)
    write(out / 'values.yaml', {
        'apiVersion': 'cli.kyverno.io/v1alpha1', 'kind': 'Values',
        'metadata': {'name': 'delivery'},
        'namespaceSelector': [{'name': 'ksp-demo', 'labels': {
            'ksp.io/environment': 'production', 'ksp.io/profile': 'restricted'}}]})
    policies = sorted((FRAMEWORK / 'tests/e2e_env/production/policies').glob('*/*.yaml'))
    if len(policies) != 29:
        raise SystemExit('Expected 29 production policies including common META-003')
    results = []
    kinds = {'pods': ('Pod', 'demo-app-preflight'),
             'deployments': ('Deployment', 'demo-app'),
             'namespaces': ('Namespace', 'ksp-demo')}
    for path in policies:
        policy = yaml.safe_load(path.read_text())
        if policy['kind'] not in ('ValidatingPolicy', 'ImageValidatingPolicy'):
            continue  # Opt-in generation/mutation is still loaded, but not enabled for this namespace.
        matched = {r for rule in policy['spec']['matchConstraints']['resourceRules'] for r in rule['resources']}
        for resource_type, (kind, name) in kinds.items():
            if resource_type in matched:
                results.append({'policy': policy['metadata']['name'],
                                'rule': policy['metadata']['name'], 'kind': kind,
                                'resources': [name], 'result': 'pass'})
    write(out / 'kyverno-test.yaml', {
        'apiVersion': 'cli.kyverno.io/v1alpha1', 'kind': 'Test',
        'metadata': {'name': 'delivery-production-restricted'},
        'policies': [str(p.resolve()) for p in policies],
        'resources': ['namespace.yaml', 'deployment.yaml', 'pod.yaml', 'service.yaml'],
        'variables': 'values.yaml', 'results': results})


def helm_resources(source, destination):
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    resources = []
    for obj in yaml.safe_load_all(Path(source).read_text()):
        if not obj:
            continue
        resources.append(obj)
        # Agents are runtime PodTemplates stored in JCasC, not Helm Pod objects.
        if obj.get('kind') == 'ConfigMap':
            for value in obj.get('data', {}).values():
                if 'clouds:' not in value:
                    continue
                casc = yaml.safe_load(value)
                for cloud in casc.get('jenkins', {}).get('clouds', []):
                    kubernetes = cloud.get('kubernetes', {})
                    for template in kubernetes.get('templates', []):
                        agent = yaml.safe_load(template.get('yaml', '')) or {'apiVersion': 'v1', 'kind': 'Pod', 'spec': {}}
                        agent['metadata'] = {'name': 'jenkins-agent-preflight', 'namespace': 'jenkins',
                                             'labels': {p['key']: p['value'] for p in kubernetes.get('podLabels', [])}}
                        containers = {c['name']: c for c in agent['spec'].get('containers', [])}
                        for c in template.get('containers', []):
                            container = containers.setdefault(c['name'], {'name': c['name']})
                            container['image'] = c['image']
                            container['resources'] = {
                                'requests': {'cpu': str(c['resourceRequestCpu']), 'memory': str(c['resourceRequestMemory'])},
                                'limits': {'cpu': str(c['resourceLimitCpu']), 'memory': str(c['resourceLimitMemory'])}}
                        agent['spec']['containers'] = list(containers.values())
                        resources.append(agent)
        if obj.get('kind') in ('Deployment', 'StatefulSet', 'DaemonSet', 'Job'):
            resources.append(pod_for(obj, 'jenkins'))
    (out / 'resources.yaml').write_text(yaml.safe_dump_all(resources, sort_keys=False))
    write(out / 'values.yaml', {'apiVersion': 'cli.kyverno.io/v1alpha1', 'kind': 'Values',
                              'metadata': {'name': 'jenkins-preflight'},
                              'namespaceSelector': [{'name': 'jenkins', 'labels': {
                                  'ksp.io/environment': 'production', 'ksp.io/profile': 'restricted'}}]})


if __name__ == '__main__':
    {'delivery': delivery, 'helm': helm_resources}[sys.argv[1]](*sys.argv[2:])
