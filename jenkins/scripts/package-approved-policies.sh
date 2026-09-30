#!/usr/bin/env bash
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
policy_environment="${1:-${POLICY_ENVIRONMENT:-development}}"
case "$policy_environment" in
  development|staging|production) ;;
  *) echo "Invalid POLICY_ENVIRONMENT: $policy_environment" >&2; exit 1 ;;
esac
cd "$CI_PROJECT_DIR"
# Verify environment, evidence, and bytes. Never invoke the renderer here.
python3 jenkins/scripts/approved-policies.py package "$policy_environment"
