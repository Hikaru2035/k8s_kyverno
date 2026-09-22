#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
out="$ROOT/artifacts/integration-kind"
mkdir -p "$out"
: "${KIND_CLUSTER_NAME:?unique cluster name required}"
export KUBECONFIG
KUBECONFIG="$(mktemp)"
cleanup() {
  status=$?
  trap - EXIT
  kind export logs "$out/kind-cluster-logs" --name "$KIND_CLUSTER_NAME" > "$out/export-logs.txt" 2>&1 || true
  if ! kind delete cluster --name "$KIND_CLUSTER_NAME" > "$out/cleanup.txt" 2>&1; then status=1; fi
  rm -f -- "$KUBECONFIG"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# A local runtime on an isolated host avoids GitLab's insecure remote DinD API.
kind create cluster --name "$KIND_CLUSTER_NAME" --wait 180s 2>&1 | tee "$out/kind-create.txt"
kubectl wait --for=condition=Ready node --all --timeout=120s
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update kyverno
helm install kyverno kyverno/kyverno --namespace kyverno --create-namespace \
  --version "$(version policy_engine.kyverno.chart_version)" \
  --set admissionController.replicas=1 --set backgroundController.replicas=1 \
  --set cleanupController.replicas=1 --set reportsController.replicas=1 \
  --wait --timeout 5m 2>&1 | tee "$out/kyverno-install.txt"
kubectl -n kyverno wait deployment --all --for=condition=Available --timeout=180s
bash k8s-security-framework/scripts/render-policies.sh production
bundle=k8s-security-framework/tests/e2e_env/production/policies
kubectl apply --recursive -f "$bundle" 2>&1 | tee "$out/all-policy-apply.txt"
for type in validatingpolicies imagevalidatingpolicies mutatingpolicies generatingpolicies; do
  kubectl wait "$type" --all --for=condition=Ready --timeout=180s
  kubectl get "$type" -o yaml > "$out/$type.yaml"
done
# Preserve the isolated POD-010 admission regression from GitLab.
kubectl delete --recursive -f "$bundle" --wait=true
policy="$bundle/baseline/KSP-POD-010-require-seccomp.yaml"
kubectl apply -f "$policy"
kubectl wait validatingpolicy/require-seccomp --for=condition=Ready --timeout=120s
kubectl create namespace ksp-ci
kubectl label namespace ksp-ci ksp.io/environment=production ksp.io/profile=baseline
cat > "$out/positive.yaml" <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: ksp-positive
  namespace: ksp-ci
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: registry.k8s.io/pause:3.10
YAML
python3 - "$out" <<'PY'
import sys, yaml
from pathlib import Path
out = Path(sys.argv[1])
pod = yaml.safe_load((out/'positive.yaml').read_text())
pod['metadata']['name'] = 'ksp-negative'
del pod['spec']['securityContext']
(out/'negative.yaml').write_text(yaml.safe_dump(pod))
PY
kubectl create -f "$out/positive.yaml" 2>&1 | tee "$out/positive-admission.txt"
if kubectl create -f "$out/negative.yaml" > "$out/negative-admission.txt" 2>&1; then
  echo 'ERROR: negative Pod admitted'; exit 1
fi
# Reject connection/RBAC errors as evidence of a successful negative test.
grep -qi 'denied' "$out/negative-admission.txt"
grep -qi 'require-seccomp' "$out/negative-admission.txt"
test -z "$(kubectl get pod ksp-negative -n ksp-ci --ignore-not-found -o name)"
kubectl delete pod ksp-positive -n ksp-ci --wait=true
# Additional full Baseline profile admission test; common META-003 applied once.
kubectl apply -f "$bundle/common" -f "$bundle/baseline"
kubectl wait validatingpolicies --all --for=condition=Ready --timeout=120s
kubectl wait imagevalidatingpolicies --all --for=condition=Ready --timeout=120s
bootstrap_digest="$(crane digest registry.k8s.io/pause:3.10)"
[[ "$bootstrap_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
python3 - "$out" "$bootstrap_digest" <<'PY'
import sys, yaml
from pathlib import Path
out = Path(sys.argv[1])
pod = yaml.safe_load((out/'positive.yaml').read_text())
pod['metadata']['name'] = 'ksp-baseline-positive'
pod['spec']['securityContext']['runAsUser'] = 65532
pod['spec']['containers'][0]['image'] = 'registry.k8s.io/pause@' + sys.argv[2]
pod['spec']['containers'][0]['resources'] = {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '32Mi'}}
(out/'baseline-positive.yaml').write_text(yaml.safe_dump(pod))
pod['metadata']['name'] = 'ksp-baseline-negative'
del pod['spec']['securityContext']['seccompProfile']
(out/'baseline-negative.yaml').write_text(yaml.safe_dump(pod))
PY
kubectl create -f "$out/baseline-positive.yaml" 2>&1 | tee "$out/baseline-positive-admission.txt"
if kubectl create -f "$out/baseline-negative.yaml" > "$out/baseline-negative-admission.txt" 2>&1; then exit 1; fi
grep -qi 'denied' "$out/baseline-negative-admission.txt"
grep -qi 'require-seccomp' "$out/baseline-negative-admission.txt"
test -z "$(kubectl get pod ksp-baseline-negative -n ksp-ci --ignore-not-found -o name)"
RUN_ID="$KIND_CLUSTER_NAME" ENVIRONMENT=production \
  bash k8s-security-framework/scripts/evidence/collect-evidence.sh > "$out/evidence-collection.txt" 2>&1
kubectl get pod ksp-baseline-positive -n ksp-ci -o yaml > "$out/baseline-positive-pod.yaml"
