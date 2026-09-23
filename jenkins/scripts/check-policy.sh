#!/usr/bin/env bash
# Render and drift-check exactly one environment selected by Policy CI.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
policy_environment="${1:-${POLICY_ENVIRONMENT:-development}}"
case "$policy_environment" in
  development|staging|production) ;;
  *) echo "Invalid POLICY_ENVIRONMENT: $policy_environment" >&2; exit 1 ;;
esac
cd "$CI_PROJECT_DIR"
mkdir -p artifacts/check-policy
bash k8s-security-framework/scripts/render-policies.sh "$policy_environment" \
  > "artifacts/check-policy/render-$policy_environment.txt" 2>&1
cat "artifacts/check-policy/render-$policy_environment.txt"
git status --porcelain -- "k8s-security-framework/tests/e2e_env/$policy_environment/policies" \
  > artifacts/check-policy/render-drift.txt
cat artifacts/check-policy/render-drift.txt
if test -s artifacts/check-policy/render-drift.txt; then
  echo "ERROR: selected environment rendered policy bundle is stale."
  exit 1
fi
python3 jenkins/scripts/approved-policies.py record-render "$policy_environment"
