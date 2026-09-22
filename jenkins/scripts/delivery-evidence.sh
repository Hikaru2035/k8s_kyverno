#!/usr/bin/env bash
# Collect each resource even if an earlier collection failed. Never collect Secrets.
set -euo pipefail
out="${1:?artifact directory required}"
mkdir -p "$out/policy-report" "$out/deployment"
status=0
for type in deployments replicasets pods services endpointslices events; do
  kubectl -n ksp-demo get "$type" -o json > "$out/deployment/$type.json" \
    2> "$out/deployment/$type.error.txt" || status=1
done
kubectl -n ksp-demo get policyreports -o json > "$out/policy-report/namespaced.json" \
  2> "$out/policy-report/namespaced.error.txt" || status=1
kubectl get clusterpolicyreports -o json > "$out/policy-report/cluster.json" \
  2> "$out/policy-report/cluster.error.txt" || status=1
if [[ "$status" == 0 ]]; then
  python3 - "$out" <<'PY' > "$out/policy-report/summary.json" || status=1
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
uids = set()
for kind in ('deployments', 'replicasets', 'pods'):
    for obj in json.loads((out / 'deployment' / (kind + '.json')).read_text())['items']:
        if obj['metadata'].get('labels', {}).get('app.kubernetes.io/name') == 'demo-app':
            uids.add(obj['metadata']['uid'])
related = []
for name in ('namespaced', 'cluster'):
    for report in json.loads((out / 'policy-report' / (name + '.json')).read_text())['items']:
        for result in report.get('results', []):
            refs = result.get('resources', []) + [report.get('scope', {})]
            if any(ref.get('uid') in uids for ref in refs):
                related.append({'report': report['metadata']['name'], **result})
summary = {'applicationUIDs': sorted(uids), 'results': related,
           'note': 'Reports are asynchronous; missing/skip results are not proof of policy compliance.'}
print(json.dumps(summary, indent=2))
if any(r.get('result') in ('fail', 'error') for r in related):
    raise SystemExit(1)
PY
fi
printf '%s\n' "$status" > "$out/policy-report/collection-status.txt"
exit "$status"
