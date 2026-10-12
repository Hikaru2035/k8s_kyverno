#!/usr/bin/env bash
# No Secret reads. The collector uses only the explicitly bound kubeconfig.
set +x
set -euo pipefail
: "${KUBECONFIG:?Jenkins kubeconfig credential required}"
test -f "$KUBECONFIG"
exec python3 "$(dirname "$0")/delivery-reports.py" "$@"
