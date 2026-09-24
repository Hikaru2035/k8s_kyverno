#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/common.sh"
: "${BUILD_ID:?BUILD_ID required}"
: "${BUILD_NUMBER:?BUILD_NUMBER required}"
[[ "$BUILD_ID" =~ ^[A-Za-z0-9_-]+$ && "$BUILD_NUMBER" =~ ^[0-9]+$ ]]
out="$ROOT/artifacts/delivery/$BUILD_ID"
mkdir -p "$out"/{source-check,scan,image,harbor,cosign,kyverno,deployment,policy-report,health}
export POLICY_ENVIRONMENT="${POLICY_ENVIRONMENT:-development}"
export POLICY_CI_JOB="${POLICY_CI_JOB:-automated-tested}"
: "${POLICY_CI_BUILD:?Select an explicit successful Policy CI build}"
export POLICY_CI_BUILD
case "$POLICY_ENVIRONMENT" in development|staging|production) ;; *) echo 'Invalid POLICY_ENVIRONMENT' >&2; exit 2 ;; esac
approved="$out/approved-policies-$POLICY_ENVIRONMENT"
kubectl() {
  : "${KUBECONFIG:?Jenkins kubeconfig credential required}"
  test -f "$KUBECONFIG"
  command kubectl --kubeconfig "$KUBECONFIG" --request-timeout=30s "$@"
}
# Every cluster action rechecks artifact integrity before any kubectl invocation.
case "${1:-}" in
  deploy-policies|verify-policies|admission|rollout|reports|health)
    python3 jenkins/scripts/policy_artifact.py check "$out" > /dev/null ;;
esac
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
    python3 jenkins/scripts/build-demo-image.py "$ROOT" "$out/image" "$tag" \
      2>&1 | tee "$out/image/build.txt"
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
  policy-artifact)
    python3 jenkins/scripts/policy_artifact.py fetch "$out" \
      > "$out/kyverno/artifact-retrieval.json"
    ;;
  policy-verify)
    python3 jenkins/scripts/policy_artifact.py check "$out" \
      > "$out/kyverno/artifact-verification.json"
    ;;
  deploy-policies)
    mkdir -p "$out/kyverno/approved-policies"
    kubectl config current-context > "$out/kyverno/approved-policies/context.txt"
    kubectl config view --minify -o 'jsonpath={.clusters[0].cluster.server}' \
      > "$out/kyverno/approved-policies/api-server.txt"
    kubectl get namespace kube-system -o 'jsonpath={.metadata.uid}' \
      > "$out/kyverno/approved-policies/cluster-uid.txt"
    python3 jenkins/scripts/live-policies.py apply "$approved" "$out/kyverno/approved-policies" "$POLICY_ENVIRONMENT"
    ;;
  verify-policies)
    python3 jenkins/scripts/live-policies.py verify "$approved" "$out/kyverno/approved-policies" "$POLICY_ENVIRONMENT" \
      > "$out/kyverno/approved-policies/verification.txt"
    ;;
  render)
    python3 jenkins/scripts/policy_artifact.py check "$out" > /dev/null
    python3 jenkins/scripts/manifests.py delivery "$(reference)" "$out/deployment/rendered" "$POLICY_ENVIRONMENT"
    ;;
  admission)
    # Recheck the installed set immediately before application admission.
    python3 jenkins/scripts/live-policies.py verify "$approved" "$out/kyverno/approved-policies" "$POLICY_ENVIRONMENT" \
      > "$out/kyverno/pre-admission-policy-check.txt"
    kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations -o yaml > "$out/kyverno/webhooks.yaml"
    kubectl get namespace ksp-demo --ignore-not-found -o json > "$out/deployment/namespace-before.json"
    kubectl apply -f "$out/deployment/rendered/namespace.yaml" 2>&1 | tee "$out/deployment/namespace-apply.txt"
    # Explicit Pod dry-run exercises Pod-only CEL policies before controller creation.
    kubectl create --dry-run=server -f "$out/deployment/rendered/pod.yaml" \
      -o yaml > "$out/kyverno/pod-admission.yaml" 2> "$out/kyverno/pod-admission.log"
    kubectl apply -f "$out/deployment/rendered/deployment.yaml" \
      -f "$out/deployment/rendered/service.yaml" \
      -f "$out/deployment/rendered/networkpolicy.yaml" 2>&1 | tee "$out/deployment/apply.txt"
    ;;
  rollout)
    kubectl --request-timeout=210s -n ksp-demo rollout status deployment/demo-app --timeout=180s \
      2>&1 | tee "$out/deployment/rollout.txt"
    ;;
  reports)
    bash jenkins/scripts/delivery-evidence.sh "$out" "$approved" "$POLICY_ENVIRONMENT"
    ;;
  health)
    kubectl -n ksp-demo get deployment demo-app -o json > "$out/health/deployment.json"
    kubectl --request-timeout=150s -n ksp-demo wait pod -l app.kubernetes.io/name=demo-app --for=condition=Ready --timeout=120s
    kubectl -n ksp-demo get pods -l app.kubernetes.io/name=demo-app -o json > "$out/health/pods.json"
    kubectl -n ksp-demo get service demo-app -o json > "$out/health/service.json"
    kubectl -n ksp-demo get endpointslices -l kubernetes.io/service-name=demo-app -o json > "$out/health/endpointslices.json"
    python3 jenkins/scripts/health-check.py "$out/health" "$(reference)"
    # Ready Pods have passed the application's HTTP readiness probe; no ingress is required.
    ;;
  *) echo 'Unknown delivery stage' >&2; exit 2 ;;
esac
