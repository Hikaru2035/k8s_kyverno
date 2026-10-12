#!/usr/bin/env python3
"""Replace exactly the demo Deployment's app image scalar, preserving other bytes."""
import argparse
from pathlib import Path
import re
import yaml
from policy_artifact import require

REFERENCE = r'harbor-public:30003/ksp-test/demo-app@sha256:[0-9a-f]{64}'


def field(node, key):
    require(isinstance(node, yaml.MappingNode), 'Expected YAML mapping')
    matches = [value for name, value in node.value if name.value == key]
    require(len(matches) == 1, f'Missing/duplicate YAML field: {key}')
    return matches[0]


def update(reference_file, deployment):
    reference = Path(reference_file).read_text().strip()
    require(re.fullmatch(REFERENCE, reference), 'Expected immutable Harbor demo-app SHA256 reference')
    require(reference.rsplit(':',1)[1] != '0'*64, 'Bootstrap digest is not a publishable image')
    path = Path(deployment)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Symlink deployment path')
    before = path.read_bytes().decode('utf-8')
    node = yaml.compose(before)
    require(field(node,'apiVersion').value == 'apps/v1' and field(node,'kind').value == 'Deployment', 'Expected Deployment')
    metadata = field(node,'metadata')
    require(field(metadata,'name').value == 'demo-app' and field(metadata,'namespace').value == 'ksp-demo', 'Unexpected Deployment identity')
    containers = field(field(field(field(node,'spec'),'template'),'spec'),'containers')
    require(isinstance(containers,yaml.SequenceNode), 'Expected containers list')
    matches = [c for c in containers.value if field(c,'name').value == 'app']
    require(len(matches) == 1, 'Expected exactly one app container')
    scalar = field(matches[0],'image')
    require(isinstance(scalar,yaml.ScalarNode) and not scalar.style, 'Expected plain image scalar')
    require(before[scalar.start_mark.index:scalar.end_mark.index] == scalar.value, 'Aliased/anchored image unsupported')
    after = before[:scalar.start_mark.index] + reference + before[scalar.end_mark.index:]
    expected = yaml.safe_load(before)
    target = next(c for c in expected['spec']['template']['spec']['containers'] if c['name']=='app')
    target['image'] = reference
    require(yaml.safe_load(after) == expected, 'Image edit changed unrelated YAML')
    path.write_bytes(after.encode('utf-8'))
    return dict(image=reference)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference'); parser.add_argument('deployment')
    args = parser.parse_args()
    try:
        import json
        print(json.dumps(update(args.reference,args.deployment),indent=2))
    except (ValueError,OSError,yaml.YAMLError) as error:
        raise SystemExit(str(error))
