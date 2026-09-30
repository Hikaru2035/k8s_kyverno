#!/usr/bin/env bash
set +x
set -euo pipefail
source "$(dirname "$0")/common.sh"
: "${BUILD_ID:?}" "${POLICY_CI_JOB:?}" "${POLICY_CI_BUILD:?Select an explicit successful Policy CI build}"
[[ "$BUILD_ID" =~ ^[A-Za-z0-9_-]+$ && "$POLICY_CI_BUILD" =~ ^[1-9][0-9]*$ ]]
export POLICY_ENVIRONMENT="${POLICY_ENVIRONMENT:-development}"
export POLICY_PROFILE="${POLICY_PROFILE:-baseline}"
[[ "$POLICY_ENVIRONMENT" == development ]]
case "$POLICY_PROFILE" in baseline|standard|restricted) ;; *) exit 2 ;; esac
out="$ROOT/artifacts/policy-promotion/$BUILD_ID"
case "${1:?stage required}" in
  initialize) test ! -e "$out"; mkdir -p "$out" ;;
  fetch) python3 jenkins/scripts/policy_artifact.py fetch "$out" > "$out/retrieval.json" ;;
  verify) python3 jenkins/scripts/policy_artifact.py check "$out" > "$out/verification.json" ;;
  prepare) python3 jenkins/scripts/gitops_publish.py prepare policy "$out/gitops" ;;
  promote)
    python3 jenkins/scripts/gitops_policy.py "$out" \
      "${GITOPS_CHECKOUT:-.gitops-publish}/gitops/policies/development" > "$out/promotion.json"
    ;;
  publish) python3 jenkins/scripts/gitops_publish.py publish policy "$out/gitops" ;;
  *) echo 'Unknown promotion stage' >&2; exit 2 ;;
esac
