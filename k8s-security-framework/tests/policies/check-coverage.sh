#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRAMEWORK_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PRODUCTION_PROFILE="${FRAMEWORK_ROOT}/profiles/restricted/policy-ids.txt"
POLICIES_ROOT="${FRAMEWORK_ROOT}/policies"
EXPECTED_POLICY_COUNT="${EXPECTED_POLICY_COUNT:-30}"

if [[ ! -f "${PRODUCTION_PROFILE}" ]]; then
  echo "ERROR: missing production profile: ${PRODUCTION_PROFILE}"
  exit 1
fi

if [[ ! -d "${POLICIES_ROOT}" ]]; then
  echo "ERROR: missing policies directory: ${POLICIES_ROOT}"
  exit 1
fi

mapfile -t POLICY_IDS < <(grep -E '^[A-Z0-9-]+$' "${PRODUCTION_PROFILE}")

errors=0

echo "Checking production-candidate CLI test coverage..."
echo "Profile source: ${PRODUCTION_PROFILE}"
echo "Policies declared: ${#POLICY_IDS[@]}"

if [[ "${#POLICY_IDS[@]}" -ne "${EXPECTED_POLICY_COUNT}" ]]; then
  echo "ERROR: expected ${EXPECTED_POLICY_COUNT} production-candidate policies, found ${#POLICY_IDS[@]}"
  errors=$((errors + 1))
fi

for policy_id in "${POLICY_IDS[@]}"; do
  mapfile -t matches < <(find "${POLICIES_ROOT}" -type d -name "${policy_id}" -print)

  if [[ "${#matches[@]}" -eq 0 ]]; then
    echo "FAIL ${policy_id}: policy directory not found"
    errors=$((errors + 1))
    continue
  fi

  if [[ "${#matches[@]}" -gt 1 ]]; then
    echo "FAIL ${policy_id}: multiple policy directories found"
    printf '  %s\n' "${matches[@]}"
    errors=$((errors + 1))
    continue
  fi

  policy_dir="${matches[0]}"
  tests_dir="${policy_dir}/tests"
  test_manifest="${tests_dir}/kyverno-test.yaml"

  policy_errors=0

  if [[ ! -f "${test_manifest}" ]]; then
    echo "FAIL ${policy_id}: missing tests/kyverno-test.yaml"
    errors=$((errors + 1))
    continue
  fi

  policy_file=$(find "${policy_dir}" -maxdepth 1 -type f -name "${policy_id}-*.yaml" -print -quit)
  exception_mode=$(sed -n 's/^[[:space:]]*policies.ksp.io\/exception:[[:space:]]*//p' "${policy_file}" | head -n 1)

  required_categories=(positive negative boundary)
  if [[ "${exception_mode}" != "none" ]]; then
    required_categories+=(exception)
  fi

  for category in "${required_categories[@]}"; do
    if ! find "${tests_dir}" -maxdepth 1 -type f \
      \( -name "${category}-*.yaml" -o -name "${category}-*.yml" \) \
      -print -quit | grep -q .; then
      echo "FAIL ${policy_id}: missing ${category}-* fixture"
      errors=$((errors + 1))
      policy_errors=$((policy_errors + 1))
    fi
  done

  if [[ "${policy_errors}" -eq 0 ]]; then
    echo "PASS ${policy_id}"
  fi
done

echo
if [[ "${errors}" -ne 0 ]]; then
  echo "Coverage check FAILED: ${errors} problem(s) found."
  exit 1
fi

echo "Coverage check PASSED: ${#POLICY_IDS[@]}/${#POLICY_IDS[@]} production-candidate policies meet the required CLI test structure."
