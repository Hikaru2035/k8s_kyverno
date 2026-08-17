#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
policy_dir="$project_dir/policies"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

mapfile -t policy_files < <(find "$policy_dir" -mindepth 3 -maxdepth 3 -type f -name 'KSP-*.yaml' | sort)
[[ ${#policy_files[@]} -eq 29 ]] || fail "expected 29 policy files, found ${#policy_files[@]}"

mapfile -t all_ids < <(printf '%s\n' "${policy_files[@]}" | sed -E 's#.*/(KSP-[A-Z]+-[0-9]{3})/.*#\1#')
[[ $(printf '%s\n' "${all_ids[@]}" | sort -u | wc -l) -eq 29 ]] || fail "duplicate policy ID"

for file in "${policy_files[@]}"; do
  folder=$(basename "$(dirname "$file")")
  [[ $(basename "$file") == "$folder"-* ]] || fail "filename does not start with folder ID: $file"
  grep -q '^apiVersion: kyverno.io/v1$' "$file" || fail "wrong apiVersion: $file"
  grep -q '^kind: ClusterPolicy$' "$file" || fail "wrong kind: $file"
  grep -q 'policies.kyverno.io/severity:' "$file" || fail "missing severity: $file"
done

validate_profile() {
  local profile=$1
  local expected=$2
  local list="$project_dir/profiles/$profile/policy-ids.txt"
  [[ -f $list ]] || fail "missing profile list: $list"
  [[ $(sort -u "$list" | wc -l) -eq $expected ]] || fail "$profile must contain $expected unique IDs"
  if comm -23 <(sort -u "$list") <(printf '%s\n' "${all_ids[@]}" | sort -u) | grep -q .; then
    fail "$profile contains unknown ID"
  fi
}

validate_profile baseline 10
validate_profile standard 22
validate_profile restricted 29
if comm -23 <(sort -u "$project_dir/profiles/baseline/policy-ids.txt") <(sort -u "$project_dir/profiles/standard/policy-ids.txt") | grep -q .; then
  fail "standard is not a baseline superset"
fi
if comm -23 <(sort -u "$project_dir/profiles/standard/policy-ids.txt") <(sort -u "$project_dir/profiles/restricted/policy-ids.txt") | grep -q .; then
  fail "restricted is not a standard superset"
fi

required_keys=(ENVIRONMENT PROFILE APPROVED_REGISTRIES SIGNED_IMAGE_PATTERNS COSIGN_PUBLIC_KEY_FILE OWNER_LABEL_KEY ENVIRONMENT_LABEL_KEY EXCLUDED_NAMESPACES QUOTA_REQUESTS_CPU QUOTA_REQUESTS_MEMORY QUOTA_LIMITS_CPU QUOTA_LIMITS_MEMORY QUOTA_PODS LIMIT_DEFAULT_REQUEST_CPU LIMIT_DEFAULT_REQUEST_MEMORY LIMIT_DEFAULT_CPU LIMIT_DEFAULT_MEMORY LIMIT_MIN_CPU LIMIT_MIN_MEMORY LIMIT_MAX_CPU LIMIT_MAX_MEMORY WEBHOOK_TIMEOUT_SECONDS VERIFY_IMAGE_TIMEOUT_SECONDS FAILURE_POLICY_CRITICAL FAILURE_POLICY_DEFAULT AUDIT_MIN_DAYS MAX_VIOLATION_RATE MAX_FALSE_POSITIVE_RATE MAX_EXCEPTION_RATE MAX_ADMISSION_P95_MS MAX_WEBHOOK_ERROR_RATE)

for environment in development staging production; do
  env_file="$project_dir/environments/$environment/parameters.env"
  [[ -f $env_file ]] || fail "missing $env_file"
  for key in "${required_keys[@]}"; do
    grep -q "^${key}=" "$env_file" || fail "$environment missing $key"
  done
  env_name=$(sed -n 's/^ENVIRONMENT=//p' "$env_file")
  profile=$(sed -n 's/^PROFILE=//p' "$env_file")
  [[ $env_name == "$environment" ]] || fail "ENVIRONMENT mismatch in $env_file"
  [[ $profile =~ ^(baseline|standard|restricted)$ ]] || fail "invalid PROFILE in $env_file"
  grep -Eq '^FAILURE_POLICY_CRITICAL=(Fail|Ignore)$' "$env_file" || fail "invalid critical failure policy"
  grep -Eq '^FAILURE_POLICY_DEFAULT=(Fail|Ignore)$' "$env_file" || fail "invalid default failure policy"
done

grep -q '^FAILURE_POLICY_CRITICAL=Fail$' "$project_dir/environments/production/parameters.env" || fail "production critical policy must fail closed"
echo "PASS: 29 policies; profiles 10/22/29; environment parameter schema complete"
