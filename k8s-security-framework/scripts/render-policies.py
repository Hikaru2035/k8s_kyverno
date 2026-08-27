#!/usr/bin/env python3
"""Deterministically render one self-contained cluster E2E policy bundle."""
from pathlib import Path
import shutil, sys, yaml

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    "development": ("dev", "dev-mode"),
    "staging": ("staging", "staging-mode"),
    "production": ("production", "prod-mode"),
}
PLATFORM = []

def ids(profile):
    return [x.strip() for x in (ROOT / "profiles" / profile / "policy-ids.txt").read_text().splitlines() if x.strip()]

def source(policy_id):
    found = list((ROOT / "policies").glob(f"*/{policy_id}/{policy_id}-*.yaml"))
    if len(found) != 1: raise SystemExit(f"expected one source for {policy_id}, found {len(found)}")
    return found[0]

def condition_for(level, namespace_policy):
    if level == "baseline" or not namespace_policy: profile = "true"
    elif level == "standard": profile = "object.metadata.?labels['ksp.io/profile'].orValue('') in ['standard', 'restricted']"
    else: profile = "object.metadata.?labels['ksp.io/profile'].orValue('') == 'restricted'"
    platform = f"!(object.metadata.name in {PLATFORM!r})" if namespace_policy else f"!(request.namespace in {PLATFORM!r})"
    return f"({profile}) && ({platform})"

def render(policy_id, level, env_name):
    env_value, mode_key = ENV[env_name]
    src = source(policy_id)
    data = yaml.safe_load(src.read_text())
    annotations = data["metadata"]["annotations"]
    mode = annotations[f"policies.ksp.io/{mode_key}"]
    kind = data["kind"]
    if kind in ("ValidatingPolicy", "ImageValidatingPolicy"):
        data["spec"]["validationActions"] = ["Deny"] if mode in ("Enforce", "Audit/Enforce") else ["Audit", "Warn"]
    elif kind == "MutatingPolicy" and mode in ("Audit", "Disabled"):
        data["spec"].setdefault("evaluation", {}).setdefault("admission", {})["enabled"] = False
    data["metadata"]["annotations"]["policies.ksp.io/rendered-from"] = str(src.relative_to(ROOT))
    data["metadata"]["annotations"]["policies.ksp.io/runtime-environment"] = env_name
    rules = data.get("spec", {}).get("matchConstraints", {}).get("resourceRules", [])
    namespace_policy = any("namespaces" in r.get("resources", []) for r in rules)
    if not namespace_policy and level in ("standard", "restricted"):
        selector = data["spec"]["matchConstraints"].setdefault("namespaceSelector", {})
        selector.setdefault("matchExpressions", []).append({
            "key": "ksp.io/profile", "operator": "In",
            "values": ["standard", "restricted"] if level == "standard" else ["restricted"]})
    conditions = data["spec"].setdefault("matchConditions", [])
    conditions.append({"name": "ksp-runtime-profile-and-platform-scope", "expression": condition_for(level, namespace_policy)})
    if policy_id == "KSP-META-003":
        conditions.pop()
        if not conditions: data["spec"].pop("matchConditions")
        data["spec"]["matchConstraints"]["excludeResourceRules"][0]["resourceNames"] = PLATFORM
        data["spec"]["validations"][0]["expression"] = f"object.metadata.?labels['ksp.io/environment'].orValue('') == '{env_value}'"
        data["spec"]["validations"][0]["message"] = f"Set ksp.io/environment to {env_value} for this {env_name} cluster."
    return "# Generated; edit the source identified by policies.ksp.io/rendered-from.\n" + yaml.safe_dump(data, sort_keys=False)

def main():
    global PLATFORM
    if len(sys.argv) != 2 or sys.argv[1] not in ENV: raise SystemExit("usage: render-policies.py development|staging|production")
    env_name = sys.argv[1]; out = ROOT / "e2e_env" / env_name
    config = out / "platform-namespaces.yaml"
    if not config.exists(): raise SystemExit(f"missing platform exemption config: {config}")
    PLATFORM = yaml.safe_load(config.read_text())["platformNamespaces"]
    for part in ("common", "baseline", "standard", "restricted"):
        target = out / "policies" / part
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.yaml"): old.unlink()
    sets = {"baseline": ids("baseline"), "standard": ids("standard"), "restricted": ids("restricted")}
    incremental = {"baseline": sets["baseline"], "standard": [x for x in sets["standard"] if x not in sets["baseline"]], "restricted": [x for x in sets["restricted"] if x not in sets["standard"]]}
    jobs = [("common", "KSP-META-003")]
    jobs += [(level, p) for level in ("baseline", "standard", "restricted") for p in incremental[level]]
    for level, policy_id in jobs:
        content = render(policy_id, level, env_name)
        if content is not None: (out / "policies" / level / source(policy_id).name).write_text(content)
    print(f"rendered {env_name}: common=1 baseline={len(incremental['baseline'])} standard={len(incremental['standard'])} restricted={len(incremental['restricted'])}")

if __name__ == "__main__": main()
