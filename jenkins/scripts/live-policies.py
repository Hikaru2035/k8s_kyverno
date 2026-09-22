#!/usr/bin/env python3
"""Fail closed if deployed production policies differ from the rendered bundle."""
import json
import sys
from pathlib import Path
import yaml


def normalized(value):
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()
                if not (key == 'matchPolicy' and item == 'Equivalent')
                and not (key == 'scope' and item == '*')
                and not (key in ('namespaceSelector', 'objectSelector') and not item)}
    return value


def check(live, paths):
    indexed = {(item['kind'], item['metadata']['name']): item for item in live['items']}
    count = 0
    for path in paths:
        desired = yaml.safe_load(path.read_text())
        key = (desired['kind'], desired['metadata']['name'])
        actual = indexed.get(key)
        if actual is None:
            raise ValueError(f'Missing policy: {key}')
        # Server defaulted top-level spec keys are tolerated. Every supplied field
        # (including matching, exclusions, actions and key material) must be identical.
        for field, value in desired['spec'].items():
            if normalized(actual['spec'].get(field)) != normalized(value):
                raise ValueError(f'Policy drift: {key} spec.{field}')
        if (desired['kind'] in ('ValidatingPolicy', 'ImageValidatingPolicy')
                and actual['spec'].get('evaluation', {}).get('admission', {}).get('enabled') is False):
            raise ValueError(f'Admission disabled: {key}')
        if actual['spec'].get('failurePolicy', 'Fail') != 'Fail':
            raise ValueError(f'Failure policy is not Fail: {key}')
        if not any(c.get('type') == 'Ready' and c.get('status') == 'True'
                   for c in actual.get('status', {}).get('conditions', [])):
            raise ValueError(f'Policy not Ready: {key}')
        count += 1
    if count != 29:
        raise ValueError(f'Expected 29 production policies, found {count}')
    print(f'{count} live policy specs match the rendered production bundle and are Ready')


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    check(json.load(open(sys.argv[1])), sorted((root / 'k8s-security-framework/tests/e2e_env/production/policies').glob('*/*.yaml')))
