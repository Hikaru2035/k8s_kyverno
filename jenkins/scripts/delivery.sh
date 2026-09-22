#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/common.sh"
: "${BUILD_ID:?BUILD_ID required}"
: "${BUILD_NUMBER:?BUILD_NUMBER required}"
[[ "$BUILD_ID" =~ ^[A-Za-z0-9_-]+$ && "$BUILD_NUMBER" =~ ^[0-9]+$ ]]
out="$ROOT/artifacts/delivery/$BUILD_ID"
mkdir -p "$out"/{source-check,scan,image,harbor,cosign,kyverno,deployment,policy-report,health}
tag="harbor-public:30003/ksp-test/demo-app:$BUILD_NUMBER"
reference() { cat "$out/image/reference.txt"; }
case "${1:?stage required}" in
  source)
    python3 - <<'PY' > "$out/source-check/results.txt"
import ast
from pathlib import Path
import yaml
ast.parse(Path('demo-app/src/app.py').read_text())
for path in Path('demo-app/k8s').glob('*.yaml'):
    assert isinstance(yaml.safe_load(path.read_text()), dict), path
print('Python syntax and Kubernetes YAML parsed successfully')
PY
    git rev-parse HEAD > "$out/source-check/commit.txt"
    ;;
  security-scan)
    # A single lightweight scanner covers source secrets/config and image CVEs.
    trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 \
      --format json --output "$out/scan/source.json" demo-app
    ;;
  build)
    : "${BUILDKIT_HOST:?mTLS BuildKit endpoint required}"
    : "${BUILDKIT_CA:?}" "${BUILDKIT_CERT:?}" "${BUILDKIT_KEY:?}"
    [[ "$BUILDKIT_HOST" == tcp://* ]]
    buildctl --addr "$BUILDKIT_HOST" --tlscacert "$BUILDKIT_CA" \
      --tlscert "$BUILDKIT_CERT" --tlskey "$BUILDKIT_KEY" build \
      --frontend dockerfile.v0 --local context=demo-app --local dockerfile=demo-app \
      --opt "build-arg:BASE_IMAGE=$(version ci.python.image)" --opt platform=linux/amd64 \
      --output "type=docker,name=$tag,dest=$out/image/image.tar" \
      --metadata-file "$out/image/build-metadata.json" 2>&1 | tee "$out/image/build.txt"
    sha256sum "$out/image/image.tar" > "$out/image/archive.sha256"
    ;;
  image-scan)
    trivy image --input "$out/image/image.tar" --scanners vuln --severity HIGH,CRITICAL \
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
  render)
    bash k8s-security-framework/scripts/render-policies.sh production
    python3 jenkins/scripts/manifests.py delivery "$(reference)" "$out/deployment/rendered"
    ;;
  preflight)
    # Explicit expected passes prevent a skipped/non-matching policy from passing the gate.
    kyverno test "$out/deployment/rendered" --registry --require-tests --remove-color \
      --detailed-results 2>&1 | tee "$out/kyverno/pre-deployment.txt"
    ;;
  admission)
    kubectl get validatingpolicies,imagevalidatingpolicies,mutatingpolicies,generatingpolicies \
      -o json > "$out/kyverno/live-policies.json"
    python3 jenkins/scripts/live-policies.py "$out/kyverno/live-policies.json" > "$out/kyverno/live-check.txt"
    kubectl get validatingwebhookconfigurations -o yaml > "$out/kyverno/webhooks.yaml"
    # Namespace must already exist, with pull credentials provisioned by the operator.
    kubectl get namespace ksp-demo -o json > "$out/deployment/namespace-before.json"
    python3 - "$out/deployment/namespace-before.json" <<'PY'
import json, sys
labels = json.load(open(sys.argv[1]))['metadata']['labels']
assert labels.get('ksp.io/profile') == 'restricted', 'namespace must remain Restricted'
assert labels.get('ksp.io/environment') == 'production', 'namespace must remain production'
PY
    kubectl apply -f "$out/deployment/rendered/namespace.yaml" 2>&1 | tee "$out/deployment/namespace-apply.txt"
    # Explicit Pod dry-run exercises Pod-only CEL policies before controller creation.
    kubectl create --dry-run=server -f "$out/deployment/rendered/pod.yaml" \
      -o yaml > "$out/kyverno/pod-admission.yaml"
    kubectl apply -f "$out/deployment/rendered/deployment.yaml" \
      -f "$out/deployment/rendered/service.yaml" \
      -f "$out/deployment/rendered/networkpolicy.yaml" 2>&1 | tee "$out/deployment/apply.txt"
    ;;
  rollout)
    kubectl -n ksp-demo rollout status deployment/demo-app --timeout=180s \
      2>&1 | tee "$out/deployment/rollout.txt"
    ;;
  reports)
    bash jenkins/scripts/delivery-evidence.sh "$out"
    ;;
  health)
    kubectl -n ksp-demo get deployment demo-app -o json > "$out/health/deployment.json"
    kubectl -n ksp-demo wait pod -l app.kubernetes.io/name=demo-app --for=condition=Ready --timeout=120s
    kubectl -n ksp-demo get pods -l app.kubernetes.io/name=demo-app -o json > "$out/health/pods.json"
    kubectl -n ksp-demo get service demo-app -o json > "$out/health/service.json"
    kubectl -n ksp-demo get endpointslices -l kubernetes.io/service-name=demo-app -o json > "$out/health/endpointslices.json"
    python3 jenkins/scripts/health-check.py "$out/health" "$(reference)"
    # Agent runs inside the cluster: test the Service's actual DNS/network path.
    curl --fail --silent --show-error --retry 5 --retry-delay 2 --max-time 10 \
      http://demo-app.ksp-demo.svc.cluster.local:8080/healthz > "$out/health/response.json"
    python3 - "$out/health/response.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1])) == {'status': 'ok'}
PY
    ;;
  *) echo 'Unknown delivery stage' >&2; exit 2 ;;
esac
