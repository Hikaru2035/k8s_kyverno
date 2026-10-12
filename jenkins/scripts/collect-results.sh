#!/usr/bin/env bash
# Extracted from .gitlab-ci.yml; preserve test decisions and report conventions.
set -euo pipefail
export CI_PROJECT_DIR="${CI_PROJECT_DIR:-$(pwd)}"
export FRAMEWORK_ROOT=k8s-security-framework
mkdir -p "$CI_PROJECT_DIR/artifacts/report"
set -eu

framework="$CI_PROJECT_DIR/$FRAMEWORK_ROOT"

report_root="$CI_PROJECT_DIR/artifacts/report"

mkdir -p \
  "$report_root/validate" \
  "$report_root/check-policy" \
  "$report_root/cli-unit" \
  "$report_root/rendered-policy-test" \
  "$report_root/integration-kind"

if test -d "$CI_PROJECT_DIR/artifacts/validate"
then
  cp -R \
    "$CI_PROJECT_DIR/artifacts/validate/." \
    "$report_root/validate/"
fi

if test -d "$CI_PROJECT_DIR/artifacts/check-policy"
then
  cp -R \
    "$CI_PROJECT_DIR/artifacts/check-policy/." \
    "$report_root/check-policy/"
fi

if test -d "$CI_PROJECT_DIR/artifacts/cli-unit"
then
  cp -R \
    "$CI_PROJECT_DIR/artifacts/cli-unit/." \
    "$report_root/cli-unit/"
fi

if test -d "$CI_PROJECT_DIR/artifacts/rendered-policy-test"
then
  cp -R \
    "$CI_PROJECT_DIR/artifacts/rendered-policy-test/." \
    "$report_root/rendered-policy-test/"
fi

if test -d "$CI_PROJECT_DIR/artifacts/integration-kind"
then
  cp -R \
    "$CI_PROJECT_DIR/artifacts/integration-kind/." \
    "$report_root/integration-kind/"
fi

find "$report_root" \
  -type f \
  -print \
  | sort \
  > "$report_root/manifest.txt"

cat "$report_root/manifest.txt"

