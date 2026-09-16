#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 - "${SCRIPT_DIR}/../../../profiles/baseline/policy-ids.txt" <<'PY'
from pathlib import Path
import sys

# Acceptance contract; production mapping remains in profiles/.
expected = set("""
KSP-META-001 KSP-META-002 KSP-META-003
KSP-IMG-001 KSP-IMG-003 KSP-IMG-004
KSP-RES-001 KSP-RES-002 KSP-RES-003 KSP-RES-004 KSP-RES-005
KSP-POD-010 KSP-POD-013
""".split())
actual = set(Path(sys.argv[1]).read_text().split())
assert actual == expected, f"baseline mismatch: missing={expected - actual}, extra={actual - expected}"
PY
exec bash "${SCRIPT_DIR}/run.sh" baseline "$@"
