#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

POLICIES_ROOT="${FRAMEWORK_ROOT}/policies"
REPORT_ROOT="${REPORT_ROOT:-${FRAMEWORK_ROOT}/artifacts/cli-unit/regression}"
EXPECTED_POLICY_COUNT="${EXPECTED_POLICY_COUNT:-30}"

if ! command -v kyverno >/dev/null 2>&1; then
  echo "ERROR: kyverno CLI not found in PATH"
  exit 1
fi

if [[ ! -d "${POLICIES_ROOT}" ]]; then
  echo "ERROR: missing policies directory: ${POLICIES_ROOT}"
  exit 1
fi

mapfile -t TEST_MANIFESTS < <(
  find "${POLICIES_ROOT}" -type f -path '*/tests/kyverno-test.yaml' -print | sort
)

if [[ "${#TEST_MANIFESTS[@]}" -ne "${EXPECTED_POLICY_COUNT}" ]]; then
  echo "ERROR: expected ${EXPECTED_POLICY_COUNT} kyverno-test.yaml files, found ${#TEST_MANIFESTS[@]}"
  echo "Run tests/policies/check-coverage.sh first."
  exit 1
fi

mkdir -p "${REPORT_ROOT}"

passed=0
failed=0

echo "Running full Kyverno CLI regression suite..."
echo "Test suites: ${#TEST_MANIFESTS[@]}"
echo "Reports: ${REPORT_ROOT}"
echo

for manifest in "${TEST_MANIFESTS[@]}"; do
  tests_dir="$(dirname "${manifest}")"
  policy_dir="$(dirname "${tests_dir}")"
  policy_id="$(basename "${policy_dir}")"
  report_file="${REPORT_ROOT}/${policy_id}.txt"

  echo "RUN  ${policy_id}"

  if kyverno test "${tests_dir}" --detailed-results >"${report_file}" 2>&1; then
    echo "PASS ${policy_id}"
    passed=$((passed + 1))
  else
    echo "FAIL ${policy_id} -> ${report_file}"
    failed=$((failed + 1))
  fi
done

echo
echo "Regression summary:"
echo "  Passed: ${passed}"
echo "  Failed: ${failed}"
echo "  Total:  $((passed + failed))"

if [[ "${failed}" -ne 0 ]]; then
  exit 1
fi

echo "Full regression PASSED."
