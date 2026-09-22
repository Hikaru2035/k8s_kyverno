#!/usr/bin/env bash
# Extracted from .gitlab-ci.yml; preserve test decisions and report conventions.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
export FRAMEWORK_ROOT=k8s-security-framework
mkdir -p "$CI_PROJECT_DIR/artifacts/cli-unit"
mkdir -p "$CI_PROJECT_DIR/artifacts/cli-unit/junit"
set -u

cd "$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

kyverno version \
  > ../artifacts/cli-unit/kyverno-version.txt \
  2>&1

overall_status=0
pass_count=0
fail_count=0
EXPECTED_POLICY_COUNT=29
summary="../artifacts/cli-unit/summary.txt"
: > "$summary"

mapfile -t manifests < <(
  find policies \
    -type f \
    -path '*/tests/kyverno-test.yaml' \
    | sort
)

suite_count="${#manifests[@]}"
echo "CLI Unit executes all canonical policy suites and serves as the framework regression gate."
echo "Expected policy suites: $EXPECTED_POLICY_COUNT"
echo "Discovered policy suites: $suite_count"

if test "$suite_count" -ne "$EXPECTED_POLICY_COUNT"
then
  echo "ERROR: expected $EXPECTED_POLICY_COUNT policy suites, found $suite_count"
  exit 1
fi

for manifest in "${manifests[@]}"
do
  tests_dir="$(dirname "$manifest")"
  policy_id="$(
    basename "$(
      dirname "$tests_dir"
    )"
  )"

  echo "=================================================="
  echo "UNIT TEST: $policy_id"
  echo "=================================================="

  raw_report="../artifacts/cli-unit/junit/${policy_id}.raw.txt"
  extracted_report="../artifacts/cli-unit/junit/${policy_id}.extracted.xml"
  xml_report="../artifacts/cli-unit/junit/${policy_id}.xml"

  set +e

  kyverno test "$tests_dir" \
    --registry \
    --remove-color \
    --detailed-results \
    --require-tests \
    > "../artifacts/cli-unit/${policy_id}.txt" \
    2>&1

  text_status=$?

  kyverno test "$tests_dir" \
    --registry \
    --remove-color \
    --require-tests \
    --output-format junit \
    > "$raw_report" \
    2>&1

  junit_status=$?

  set -e

  cat "../artifacts/cli-unit/${policy_id}.txt"

  sed -n \
    '/^<?xml /,/^<\/testsuites>$/p' \
    "$raw_report" \
    > "$extracted_report"

  sed \
    's#<failure message="\([^"]*\)">#<failure message="\1" />#' \
    "$extracted_report" \
    > "$xml_report"

  rm -f "$extracted_report"

  if test "$text_status" -ne 0 \
    || test "$junit_status" -ne 0 \
    || ! test -s "$xml_report"
  then
    overall_status=1
    fail_count=$((fail_count + 1))
    printf '%s FAIL\n' "$policy_id" >> "$summary"
  else
    pass_count=$((pass_count + 1))
    printf '%s PASS\n' "$policy_id" >> "$summary"
  fi
done

printf '\nTOTAL=%s\nPASS=%s\nFAIL=%s\n' \
  "$suite_count" "$pass_count" "$fail_count" >> "$summary"
cat "$summary"

exit "$overall_status"

