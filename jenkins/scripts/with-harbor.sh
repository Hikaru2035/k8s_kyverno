#!/usr/bin/env bash
# Credentials stay in a temporary directory outside the archived workspace.
set +x
set -euo pipefail
: "${HARBOR_USERNAME:?Jenkins username binding required}"
: "${HARBOR_PASSWORD:?Jenkins password binding required}"
export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf -- "$DOCKER_CONFIG"' EXIT
umask 077
python3 - <<'PY'
import base64, json, os
from pathlib import Path
encoded = base64.b64encode((os.environ['HARBOR_USERNAME'] + ':' + os.environ['HARBOR_PASSWORD']).encode()).decode()
Path(os.environ['DOCKER_CONFIG'], 'config.json').write_text(json.dumps({'auths': {'harbor-public:30003': {'auth': encoded}}}))
PY
"$@"
