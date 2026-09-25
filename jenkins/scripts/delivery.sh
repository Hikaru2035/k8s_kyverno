#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/common.sh"
: "${BUILD_ID:?BUILD_ID required}"
: "${BUILD_NUMBER:?BUILD_NUMBER required}"
[[ "$BUILD_ID" =~ ^[A-Za-z0-9_-]+$ && "$BUILD_NUMBER" =~ ^[0-9]+$ ]]
out="$ROOT/artifacts/delivery/$BUILD_ID"
mkdir -p "$out"/{source-check,scan,image,harbor,cosign,gitops}
tag="harbor-public:30003/ksp-test/demo-app:$BUILD_NUMBER"
reference() { cat "$out/image/reference.txt"; }
case "${1:?stage required}" in
  source)
    python3 - <<'PY' > "$out/source-check/results.txt"
import ast
from pathlib import Path
import yaml
ast.parse(Path('demo-app/src/app.py').read_text())
for path in Path('gitops/applications/demo-app').glob('*.yaml'):
    assert isinstance(yaml.safe_load(path.read_text()), dict), path
print('Python syntax and Kubernetes YAML parsed successfully')
PY
    git rev-parse HEAD > "$out/source-check/commit.txt"
    ;;
  security-scan)
    # A single lightweight scanner covers source secrets/config and image CVEs.
    trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 \
      --format json --output "$out/scan/source.json" demo-app
    trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 \
      --format json --output "$out/scan/gitops.json" gitops/applications/demo-app
    ;;
  build)
    python3 jenkins/scripts/build-demo-image.py "$ROOT" "$out/image" "$tag" \
      2>&1 | tee "$out/image/build.txt"
    sha256sum "$out/image/image.tar" > "$out/image/archive.sha256"
    ;;
  image-scan)
    trivy image --input "$out/image/image.tar" --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
      --exit-code 1 --format json --output "$out/scan/image.json"
    ;;
  push)
    sha256sum --check "$out/image/archive.sha256"
    crane push "$out/image/image.tar" "$tag" 2>&1 | tee "$out/harbor/push.txt"
    ;;
  digest)
    digest="$(crane digest "$tag")"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
    # Detect concurrent tag replacement: compare remote with the scanned archive.
    local_digest="$(crane digest --tarball "$out/image/image.tar")"
    test "$digest" = "$local_digest"
    printf '%s\n' "$digest" > "$out/image/digest.txt"
    printf 'harbor-public:30003/ksp-test/demo-app@%s\n' "$digest" > "$out/image/reference.txt"
    crane manifest "$(reference)" > "$out/harbor/manifest.json"
    ;;
  sign)
    : "${COSIGN_KEY:?}" "${COSIGN_PASSWORD:?}"
    # Public-key comparison fails before signing with the wrong credential.
    cosign public-key --key "$COSIGN_KEY" > "$out/cosign/signer.pub"
    diff -u image-security/cosign/cosign.pub "$out/cosign/signer.pub"
    cosign sign --yes --key "$COSIGN_KEY" "$(reference)" > "$out/cosign/sign.txt" 2>&1
    ;;
  verify)
    cosign verify --key image-security/cosign/cosign.pub "$(reference)" \
      > "$out/cosign/verify.json" 2> "$out/cosign/verify.log"
    ;;
  gitops-update)
    python3 jenkins/scripts/gitops_app.py "$out/image/reference.txt" \
      "${GITOPS_CHECKOUT:-.gitops-publish}/gitops/applications/demo-app/deployment.yaml" \
      > "$out/gitops/image-update.json"
    ;;
  *) echo 'Unknown application CI stage' >&2; exit 2 ;;
esac
