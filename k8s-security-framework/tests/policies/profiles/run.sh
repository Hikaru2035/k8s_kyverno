#!/usr/bin/env bash
set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <baseline|standard|restricted>"
  exit 2
fi

PROFILE="$1"
shift || true

case "${PROFILE}" in
  baseline|standard|restricted)
    ;;
  *)
    echo "ERROR: unsupported profile '${PROFILE}'"
    echo "Allowed: baseline, standard, restricted"
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

PROFILE_FILE="${FRAMEWORK_ROOT}/profiles/${PROFILE}/policy-ids.txt"
POLICIES_ROOT="${FRAMEWORK_ROOT}/policies"
REPORT_ROOT="${REPORT_ROOT:-${FRAMEWORK_ROOT}/artifacts/cli-unit/profile-${PROFILE}}"

if ! command -v kyverno >/dev/null 2>&1; then
  echo "ERROR: kyverno CLI not found in PATH"
  exit 1
fi

if [[ ! -f "${PROFILE_FILE}" ]]; then
  echo "ERROR: missing profile file: ${PROFILE_FILE}"
  exit 1
fi

mapfile -t POLICY_IDS < <(grep -E '^[A-Z0-9-]+$' "${PROFILE_FILE}")

mkdir -p "${REPORT_ROOT}"

passed=0
failed=0
missing=0

echo "Running Kyverno CLI profile suite: ${PROFILE}"
echo "Profile source: ${PROFILE_FILE}"
echo "Policies: ${#POLICY_IDS[@]}"
echo "Reports: ${REPORT_ROOT}"
echo

for policy_id in "${POLICY_IDS[@]}"; do
  mapfile -t matches < <(find "${POLICIES_ROOT}" -type d -name "${policy_id}" -print)

  if [[ "${#matches[@]}" -ne 1 ]]; then
    echo "FAIL ${policy_id}: expected exactly one policy directory, found ${#matches[@]}"
    missing=$((missing + 1))
    continue
  fi

  tests_dir="${matches[0]}/tests"
  manifest="${tests_dir}/kyverno-test.yaml"
  report_file="${REPORT_ROOT}/${policy_id}.txt"

  if [[ ! -f "${manifest}" ]]; then
    echo "FAIL ${policy_id}: missing ${manifest}"
    missing=$((missing + 1))
    continue
  fi

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
echo "Profile summary: ${PROFILE}"
echo "  Passed:  ${passed}"
echo "  Failed:  ${failed}"
echo "  Missing: ${missing}"
echo "  Total:   ${#POLICY_IDS[@]}"

if [[ "${failed}" -ne 0 || "${missing}" -ne 0 ]]; then
  exit 1
fi

echo "Profile suite PASSED: ${PROFILE}."
