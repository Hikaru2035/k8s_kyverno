#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
action="${1:?render|check|install required}"
shift
out=artifacts/jenkins-helm
mkdir -p "$out"
chart="$(version jenkins.chart_version)"
case "$action" in
  render)
    helm repo add jenkins https://charts.jenkins.io
    helm repo update jenkins
    helm template jenkins jenkins/jenkins --namespace jenkins --version "$chart" \
      --include-crds -f helm/jenkins/values.yaml "$@" > "$out/chart.yaml"
    # Keep Namespace separate from the chart's first document.
    python3 - <<'PY'
from pathlib import Path
p=Path('artifacts/jenkins-helm/rendered.yaml')
p.write_text(Path('helm/jenkins/namespace.yaml').read_text()+'\n---\n'+Path('artifacts/jenkins-helm/chart.yaml').read_text())
PY
    python3 jenkins/scripts/manifests.py helm "$out/rendered.yaml" "$out/preflight"
    ;;
  check)
    test -s "$out/preflight/resources.yaml"
    bash k8s-security-framework/scripts/render-policies.sh production
    kyverno apply k8s-security-framework/tests/e2e_env/production/policies \
      --resource "$out/preflight/resources.yaml" --values-file "$out/preflight/values.yaml" \
      --registry --remove-color --detailed-results --warn-no-pass --warn-exit-code 1 \
      2>&1 | tee "$out/kyverno.txt"
    ;;
  install)
    # Installation is explicit, and repeats preflight against these exact values.
    bash "$0" render "$@"
    bash "$0" check
    kubectl apply -f helm/jenkins/namespace.yaml
    helm upgrade --install jenkins jenkins/jenkins --namespace jenkins --version "$chart" \
      -f helm/jenkins/values.yaml "$@" --wait --timeout 10m
    ;;
  *) exit 2 ;;
esac
