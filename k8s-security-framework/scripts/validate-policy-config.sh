#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for profile in baseline standard restricted; do
  test "$(sort -u "${ROOT}/profiles/${profile}/policy-ids.txt" | wc -l)" -eq "$(wc -l < "${ROOT}/profiles/${profile}/policy-ids.txt")"
done
comm -23 <(sort "${ROOT}/profiles/baseline/policy-ids.txt") <(sort "${ROOT}/profiles/standard/policy-ids.txt") | grep -q . && { echo 'baseline is not a subset of standard'; exit 1; } || true
comm -23 <(sort "${ROOT}/profiles/standard/policy-ids.txt") <(sort "${ROOT}/profiles/restricted/policy-ids.txt") | grep -q . && { echo 'standard is not a subset of restricted'; exit 1; } || true
python3 - "${ROOT}" <<'PY'
from pathlib import Path
import sys
import re
import yaml

root = Path(sys.argv[1])
profiles = {
    level: set((root / "profiles" / level / "policy-ids.txt").read_text().split())
    for level in ("baseline", "standard", "restricted")
}
sources = {}
for directory in sorted((root / "policies").glob("*/KSP-*")):
    if not directory.is_dir():
        continue
    paths = list(directory.glob(f"{directory.name}-*.yaml"))
    if len(paths) != 1 or directory.name in sources:
        raise SystemExit(f"expected one unique source for {directory.name}")
    sources[directory.name] = paths[0]
if not sources or profiles["restricted"] != set(sources):
    raise SystemExit("restricted membership must cover exactly all source policies")
if "KSP-META-003" not in profiles["baseline"]:
    raise SystemExit("bootstrap governance must belong to baseline")
for policy_id, path in sources.items():
    annotations = yaml.safe_load(path.read_text())["metadata"]["annotations"]
    actual = annotations["policies.ksp.io/profiles"].split(",")
    expected = [level for level, ids in profiles.items() if policy_id in ids]
    if actual != expected:
        raise SystemExit(f"{policy_id}: annotation {actual} differs from profiles {expected}")

versions = yaml.safe_load((root.parent / "versions.yaml").read_text())
ci_text = (root.parent / ".gitlab-ci.yml").read_text()
ci = yaml.safe_load(ci_text)
pins = {
    "KYVERNO_VERSION": "v" + versions["policy_engine"]["kyverno_cli"]["version"],
    "KYVERNO_CHART_VERSION": versions["policy_engine"]["kyverno"]["chart_version"],
    "KIND_VERSION": "v" + versions["ci"]["kind"]["version"],
}
for key, expected in pins.items():
    if ci["variables"].get(key) != expected:
        raise SystemExit(f"CI {key} differs from versions.yaml ({expected})")
helm_pins = re.findall(r'HELM_VERSION="v([^"\n]+)"', ci_text)
if helm_pins != [versions["ci"]["helm"]["version"]]:
    raise SystemExit("CI Helm differs from versions.yaml")
images = {job["image"] for job in ci.values() if isinstance(job, dict) and "image" in job}
expected_images = {versions["ci"][tool]["image"] for tool in ("python", "alpine", "docker")}
if images != expected_images:
    raise SystemExit("CI images differ from versions.yaml")
if set(re.findall(r'PyYAML==([0-9.]+)', ci_text)) != {versions["ci"]["pyyaml"]["version"]}:
    raise SystemExit("CI PyYAML differs from versions.yaml")
PY
echo "policy config valid: baseline=$(wc -l < "${ROOT}/profiles/baseline/policy-ids.txt") standard=$(wc -l < "${ROOT}/profiles/standard/policy-ids.txt") restricted=$(wc -l < "${ROOT}/profiles/restricted/policy-ids.txt") common=1"
