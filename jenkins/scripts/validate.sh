#!/usr/bin/env bash
# Extracted from .gitlab-ci.yml; preserve test decisions and report conventions.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
export FRAMEWORK_ROOT=k8s-security-framework
mkdir -p "$CI_PROJECT_DIR/artifacts/validate"
set -u
cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

set +e
bash ./scripts/validate-policy-config.sh \
  > ../artifacts/validate/policy-config.txt 2>&1
config_status=$?

set -e
cat ../artifacts/validate/policy-config.txt
test "$config_status" -eq 0

set -eu

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

EXPECTED_POLICY_COUNT=29
baseline_count="$(sort -u profiles/baseline/policy-ids.txt | wc -l | tr -d ' ')"
standard_count="$(sort -u profiles/standard/policy-ids.txt | wc -l | tr -d ' ')"
restricted_count="$(sort -u profiles/restricted/policy-ids.txt | wc -l | tr -d ' ')"
source_count="$(find policies -type d -name 'KSP-*' | wc -l | tr -d ' ')"

printf 'Profile counts: baseline=%s standard=%s restricted=%s sources=%s\n' \
  "$baseline_count" "$standard_count" "$restricted_count" "$source_count"

test "$baseline_count" -eq 13
test "$standard_count" -eq 27
test "$restricted_count" -eq "$EXPECTED_POLICY_COUNT"
test "$source_count" -eq "$EXPECTED_POLICY_COUNT"
grep -qx 'KSP-META-003' profiles/baseline/policy-ids.txt

set -u

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"
suite_count="$(
  find policies \
    -type f \
    -path '*/tests/kyverno-test.yaml' \
    | wc -l \
    | tr -d ' '
)"
echo "Policy suites found: $suite_count"

set +e

EXPECTED_POLICY_COUNT=29 \
  bash ./tests/policies/check-coverage.sh \
  > ../artifacts/validate/test-coverage.txt 2>&1

coverage_status=$?

set -e

cat ../artifacts/validate/test-coverage.txt
test "$coverage_status" -eq 0

set -u
cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

set +e

python3 "$CI_PROJECT_DIR/jenkins/scripts/validate-yaml.py" \
  > ../artifacts/validate/yaml-and-references.txt 2>&1

validation_status=$?

set -e
cat ../artifacts/validate/yaml-and-references.txt
exit "$validation_status"

