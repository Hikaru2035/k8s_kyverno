#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
version() {
  python3 - "$1" <<'PY'
import sys, yaml
value = yaml.safe_load(open('versions.yaml'))
for part in sys.argv[1].split('.'):
    value = value[part]
if value is None:
    raise SystemExit('Requested version is not pinned')
print(value)
PY
}
