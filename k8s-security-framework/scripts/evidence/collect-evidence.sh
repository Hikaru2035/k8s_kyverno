#!/usr/bin/env bash
set -euo pipefail

# Kyverno evidence collector
# Collects cluster state, PolicyReports, controller status/logs,
# Kubernetes Events, runtime policy actions, and Prometheus snapshots.
#
# Usage:
#   ./k8s-security-framework/scripts/evidence/collect-evidence.sh
#
# Optional overrides:
#   ENVIRONMENT=development \
#   RUN_ID=manual-test \
#   PROMETHEUS_URL=http://127.0.0.1:9090 \
#   LOG_SINCE=10m \
#   ./k8s-security-framework/scripts/evidence/collect-evidence.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)}"
ENVIRONMENT="${ENVIRONMENT:-unspecified}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts/e2e}"
KYVERNO_NAMESPACE="${KYVERNO_NAMESPACE:-kyverno}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
LOG_SINCE="${LOG_SINCE:-10m}"

OUTPUT_DIR="${ARTIFACT_ROOT}/${RUN_ID}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command '$1' was not found." >&2
    exit 1
  fi
}

require_command kubectl
require_command python3

if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "ERROR: cannot connect to the Kubernetes cluster using the current kubeconfig." >&2
  exit 1
fi

mkdir -p \
  "${OUTPUT_DIR}/admission" \
  "${OUTPUT_DIR}/policy-reports" \
  "${OUTPUT_DIR}/events" \
  "${OUTPUT_DIR}/kyverno" \
  "${OUTPUT_DIR}/metrics" \
  "${OUTPUT_DIR}/summary"

cat > "${OUTPUT_DIR}/summary/run-info.txt" <<EOF_INFO
run_id=${RUN_ID}
environment=${ENVIRONMENT}
timestamp_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cluster_context=$(kubectl config current-context)
kyverno_namespace=${KYVERNO_NAMESPACE}
prometheus_url=${PROMETHEUS_URL}
log_since=${LOG_SINCE}
EOF_INFO

echo "[1/6] Collecting runtime admission policy configuration..."

kubectl get validatingpolicy \
  -o custom-columns='NAME:.metadata.name,ACTIONS:.spec.validationActions' \
  > "${OUTPUT_DIR}/admission/runtime-policy-actions.txt" 2>&1 || true

kubectl get validatingpolicy -o yaml \
  > "${OUTPUT_DIR}/admission/validatingpolicies.yaml" 2>&1 || true

echo "[2/6] Collecting PolicyReports..."

kubectl get policyreport -A -o yaml \
  > "${OUTPUT_DIR}/policy-reports/policyreports.yaml" 2>&1 || true

kubectl get clusterpolicyreport -o yaml \
  > "${OUTPUT_DIR}/policy-reports/clusterpolicyreports.yaml" 2>&1 || true

echo "[3/6] Collecting Kyverno controller status and logs..."

kubectl get deployment -n "${KYVERNO_NAMESPACE}" -o wide \
  > "${OUTPUT_DIR}/kyverno/deployments.txt" 2>&1 || true

kubectl get deployment -n "${KYVERNO_NAMESPACE}" -o yaml \
  > "${OUTPUT_DIR}/kyverno/deployments.yaml" 2>&1 || true

kubectl get pods -n "${KYVERNO_NAMESPACE}" -o wide \
  > "${OUTPUT_DIR}/kyverno/pods.txt" 2>&1 || true

for controller in \
  kyverno-admission-controller \
  kyverno-background-controller \
  kyverno-reports-controller \
  kyverno-cleanup-controller
do
  log_name="${controller#kyverno-}.log"

  kubectl logs \
    -n "${KYVERNO_NAMESPACE}" \
    "deployment/${controller}" \
    --all-pods=true \
    --since="${LOG_SINCE}" \
    > "${OUTPUT_DIR}/kyverno/${log_name}" 2>&1 || true
done

echo "[4/6] Collecting Kubernetes Events..."

kubectl get events -A --sort-by='.lastTimestamp' \
  > "${OUTPUT_DIR}/events/events.txt" 2>&1 || true

kubectl get events -A -o yaml \
  > "${OUTPUT_DIR}/events/events.yaml" 2>&1 || true

echo "[5/6] Collecting Prometheus metric snapshots..."

if command -v curl >/dev/null 2>&1 && \
   curl -fsS --max-time 5 "${PROMETHEUS_URL}/-/ready" >/dev/null 2>&1; then

  prometheus_query() {
    local query="$1"
    local output="$2"

    curl -fsSG --max-time 15 \
      "${PROMETHEUS_URL}/api/v1/query" \
      --data-urlencode "query=${query}" \
      > "${OUTPUT_DIR}/metrics/${output}" 2>&1 || true
  }

  prometheus_query \
    'sum(kyverno_admission_requests_total)' \
    'admission-requests-total.json'

  prometheus_query \
    'sum by (request_allowed) (kyverno_admission_requests_total)' \
    'admission-decisions.json'

  prometheus_query \
    'histogram_quantile(0.95, sum by (le) (rate(kyverno_admission_review_duration_seconds_bucket[5m])))' \
    'admission-latency-p95.json'

  prometheus_query \
    'max by (service) (up{namespace="kyverno",service=~"kyverno-.*metrics"})' \
    'kyverno-target-health.json'

  prometheus_query \
    'kube_deployment_status_replicas_available{namespace="kyverno"}' \
    'controller-replicas-available.json'

  echo "Prometheus metrics collected successfully." \
    > "${OUTPUT_DIR}/metrics/status.txt"
else
  cat > "${OUTPUT_DIR}/metrics/status.txt" <<EOF_METRICS
SKIPPED
Prometheus was not reachable at:
${PROMETHEUS_URL}

The rest of the evidence collection completed normally.

If Prometheus is exposed through a local port-forward, run for example:
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090

Then rerun this collector.
EOF_METRICS
fi

echo "[6/6] Generating evidence summary..."

aggregate_reports() {
  local resource="$1"
  local label="$2"

  echo "${label}:"

  if ! kubectl get "${resource}" -A -o json 2>/dev/null | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

totals = {
    "pass": 0,
    "fail": 0,
    "warn": 0,
    "error": 0,
    "skip": 0,
}

for item in data.get("items", []):
    summary = item.get("summary", {}) or {}
    for key in totals:
        totals[key] += summary.get(key, 0) or 0

for key, value in totals.items():
    print(f"{key.upper()}={value}")
'; then
    echo "UNAVAILABLE"
  fi
}

{
  echo "=== Evidence Run ==="
  echo "run_id=${RUN_ID}"
  echo "environment=${ENVIRONMENT}"
  echo "timestamp_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "cluster_context=$(kubectl config current-context)"
  echo

  echo "=== Kyverno Deployments ==="
  kubectl get deployment -n "${KYVERNO_NAMESPACE}" \
    -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas,DESIRED:.spec.replicas' \
    2>/dev/null || echo "UNAVAILABLE"
  echo

  echo "=== Runtime Policy Actions ==="
  kubectl get validatingpolicy \
    -o custom-columns='NAME:.metadata.name,ACTIONS:.spec.validationActions' \
    2>/dev/null || echo "UNAVAILABLE"
  echo

  echo "=== PolicyReport Aggregate ==="
  aggregate_reports policyreport "PolicyReport totals"
  echo

  echo "=== ClusterPolicyReport Aggregate ==="
  aggregate_reports clusterpolicyreport "ClusterPolicyReport totals"
  echo

  echo "=== Metrics Collection ==="
  cat "${OUTPUT_DIR}/metrics/status.txt"
} > "${OUTPUT_DIR}/summary/evidence-summary.txt" 2>&1

echo
echo "Evidence collection complete."
echo "Run ID:     ${RUN_ID}"
echo "Environment:${ENVIRONMENT}"
echo "Output:     ${OUTPUT_DIR}"
echo
echo "Summary:"
echo "------------------------------------------------------------"
cat "${OUTPUT_DIR}/summary/evidence-summary.txt"
echo "------------------------------------------------------------"
