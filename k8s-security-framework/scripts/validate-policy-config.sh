#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for profile in baseline standard restricted; do
  test "$(sort -u "${ROOT}/profiles/${profile}/policy-ids.txt" | wc -l)" -eq "$(wc -l < "${ROOT}/profiles/${profile}/policy-ids.txt")"
done
comm -23 <(sort "${ROOT}/profiles/baseline/policy-ids.txt") <(sort "${ROOT}/profiles/standard/policy-ids.txt") | grep -q . && { echo 'baseline is not a subset of standard'; exit 1; } || true
comm -23 <(sort "${ROOT}/profiles/standard/policy-ids.txt") <(sort "${ROOT}/profiles/restricted/policy-ids.txt") | grep -q . && { echo 'standard is not a subset of restricted'; exit 1; } || true
grep -qx KSP-META-003 "${ROOT}/profiles/standard/policy-ids.txt" && { echo 'META-003 must be common'; exit 1; } || true
grep -qx KSP-META-003 "${ROOT}/profiles/restricted/policy-ids.txt" && { echo 'META-003 must be common'; exit 1; } || true
echo "policy config valid: baseline=$(wc -l < "${ROOT}/profiles/baseline/policy-ids.txt") standard=$(wc -l < "${ROOT}/profiles/standard/policy-ids.txt") restricted=$(wc -l < "${ROOT}/profiles/restricted/policy-ids.txt") common=1"
