#!/usr/bin/env bash
# Extracted from .gitlab-ci.yml; preserve test decisions and report conventions.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
export FRAMEWORK_ROOT=k8s-security-framework
mkdir -p "$CI_PROJECT_DIR/artifacts/check-policy"
set -eu

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"
python3 ./scripts/render-policies.py development \
  > ../artifacts/check-policy/render-development.txt \
  2>&1
python3 ./scripts/render-policies.py staging \
  > ../artifacts/check-policy/render-staging.txt \
  2>&1
python3 ./scripts/render-policies.py production \
  > ../artifacts/check-policy/render-production.txt \
  2>&1

cat ../artifacts/check-policy/render-development.txt
cat ../artifacts/check-policy/render-staging.txt
cat ../artifacts/check-policy/render-production.txt

set -eu

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

git status --porcelain -- tests/e2e_env \
  > ../artifacts/check-policy/render-drift.txt

cat ../artifacts/check-policy/render-drift.txt

if test -s ../artifacts/check-policy/render-drift.txt
then
  echo "ERROR: rendered tests/e2e_env policy bundle is stale."
  echo "Source of truth and deployable policies are not synchronized."
  exit 1
fi

echo "CHECK POLICY PASSED."
echo "tests/e2e_env is synchronized with policies/."

