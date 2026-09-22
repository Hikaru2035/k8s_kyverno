#!/usr/bin/env python3
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
reference = sys.argv[2]
deployment = json.loads((out / 'deployment.json').read_text())
status = deployment['status']
desired = deployment['spec']['replicas']
assert desired > 0
assert status.get('observedGeneration', 0) >= deployment['metadata']['generation']
assert status.get('availableReplicas', 0) == desired
assert status.get('updatedReplicas', 0) == desired
pods = json.loads((out / 'pods.json').read_text())['items']
assert pods, 'No application Pods'
for pod in pods:
    assert not pod['metadata'].get('deletionTimestamp'), 'Terminating Pod still present'
    assert all(c['image'] == reference for c in pod['spec']['containers']), 'Unexpected Pod image'
    containers = pod['status'].get('containerStatuses', [])
    assert len(containers) == len(pod['spec']['containers']) and all(c['ready'] for c in containers)
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status']['conditions'])
slices = json.loads((out / 'endpointslices.json').read_text())['items']
assert any(e.get('conditions', {}).get('ready') is True and e.get('addresses')
           for item in slices for e in item.get('endpoints', [])), 'No ready Service endpoint'
print('Deployment replicas, digest-pinned Pods, readiness and Service endpoints verified')
