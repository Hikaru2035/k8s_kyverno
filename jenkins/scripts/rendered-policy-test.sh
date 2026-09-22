#!/usr/bin/env bash
# Extracted from .gitlab-ci.yml; preserve test decisions and report conventions.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
export FRAMEWORK_ROOT=k8s-security-framework
mkdir -p "$CI_PROJECT_DIR/artifacts/rendered-policy-test"
set -u

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

TEST_ROOT="tests/e2e_env/production/tests/rendered"

if ! find "$TEST_ROOT" \
  -type f \
  -name kyverno-test.yaml \
  -print \
  -quit \
  | grep -q .
then
  echo "ERROR: no rendered policy tests found in $TEST_ROOT"
  exit 1
fi

find "$TEST_ROOT" \
  -type f \
  -name kyverno-test.yaml \
  | sort \
  > ../artifacts/rendered-policy-test/test-manifest.txt

cat ../artifacts/rendered-policy-test/test-manifest.txt

set +e

kyverno test "$TEST_ROOT" \
  --remove-color \
  --detailed-results \
  --require-tests \
  > ../artifacts/rendered-policy-test/results.txt \
  2>&1

rendered_test_status=$?

set -e

cat ../artifacts/rendered-policy-test/results.txt
exit "$rendered_test_status"

