#!/usr/bin/env python3
# Extracted unchanged from GitLab YAML/reference validation. Run from framework root.
from collections import Counter
from pathlib import Path
import os
import sys
import yaml

root = Path.cwd()
errors = []

scan_roots = [
    root / "policies",
    root / "tests",
    root / "template",
    root.parent / "helm",
    root.parent / "monitoring",
    root.parent / "image-security",
    root / "profiles",
]

yaml_files = [root.parent / "versions.yaml"]
for scan_root in scan_roots:
    if scan_root.exists():
        candidates = (
            list(scan_root.rglob("*.yaml"))
            + list(scan_root.rglob("*.yml"))
        )
        yaml_files.extend(
            path
            for path in candidates
            if "evidence" not in path.parts
            and "reports" not in path.parts
        )

gitlab_ci = root.parent / ".gitlab-ci.yml"
if gitlab_ci.is_file():
    yaml_files.append(gitlab_ci)

yaml_files = sorted(set(yaml_files))
documents = {}

for path in yaml_files:
    try:
        documents[path] = list(
            yaml.safe_load_all(
                path.read_text(encoding="utf-8")
            )
        )
    except (
        OSError,
        UnicodeError,
        yaml.YAMLError,
    ) as exc:
        try:
            location = path.relative_to(root.parent)
        except ValueError:
            location = path
        errors.append(
            f"invalid YAML {location}: {exc}"
        )

policy_dirs = sorted(
    path
    for path in (root / "policies").rglob("KSP-*")
    if path.is_dir()
    and (path / "tests" / "kyverno-test.yaml").is_file()
)

policy_ids = [
    path.name
    for path in policy_dirs
]

for policy_id, count in Counter(policy_ids).items():

    if count > 1:

        errors.append(
            f"duplicate policy ID: {policy_id}"
        )

policy_names = []
manifests = []

for policy_dir in policy_dirs:
    policy_id = policy_dir.name
    sources = sorted(
        policy_dir.glob(
            f"{policy_id}-*.yaml"
        )
    )
    if len(sources) != 1:
        errors.append(
            f"{policy_id}: expected one source policy, "
            f"found {len(sources)}"
        )
    elif sources[0] in documents:
        for document in documents[sources[0]]:
            if isinstance(document, dict):
                name = (
                    document
                    .get("metadata", {})
                    .get("name")
                )
                if not name:
                    errors.append(
                        f"{policy_id}: "
                        "policy metadata.name is missing"
                    )
                else:
                    policy_names.append(
                        (
                            name,
                            sources[0],
                        )
                    )

    manifest = (
        policy_dir
        / "tests"
        / "kyverno-test.yaml"
    )
    if not manifest.is_file():
        errors.append(
            f"{policy_id}: "
            "missing tests/kyverno-test.yaml"
        )
    else:
        manifests.append(manifest)

for name, count in Counter(
    name
    for name, _ in policy_names
).items():
    if count > 1:
        locations = ", ".join(
            str(path.relative_to(root))
            for candidate, path
            in policy_names
            if candidate == name
        )
        errors.append(
            "duplicate policy "
            f"metadata.name '{name}': "
            f"{locations}"
        )

if not policy_dirs:
    errors.append(
        "no source policy directories found"
    )


if len(manifests) != len(policy_dirs):
    errors.append(
        "policy/test mismatch: "
        f"{len(policy_dirs)} policy directories, "
        f"{len(manifests)} suites"
    )

list_reference_keys = (
    "policies",
    "resources",
    "exceptions",
    "targetResources",
)

scalar_reference_keys = (
    "context",
    "variables",
    "userinfo",
)

result_reference_keys = (
    "patchedResource",
    "generatedResource",
    "cloneSourceResource",
)

for manifest in manifests:
    loaded = documents.get(
        manifest,
        [],
    )

    test = (
        loaded[0]
        if loaded
        else None
    )

    if not isinstance(test, dict):
        errors.append(
            f"{manifest.relative_to(root)}: "
            "expected one Test document"
        )
        continue

    if test.get("kind") != "Test":
        errors.append(
            f"{manifest.relative_to(root)}: "
            "kind must be Test"
        )

    for key in list_reference_keys:
        references = test.get(
            key,
            [],
        )
        if references is None:
            continue

        if not isinstance(
            references,
            list,
        ):
            errors.append(
                f"{manifest.relative_to(root)}: "
                f"{key} must be a list"
            )
            continue

        for reference in references:
            if (
                not isinstance(reference, str)
                or not (
                    manifest.parent
                    / reference
                ).is_file()
            ):
                errors.append(
                    f"{manifest.relative_to(root)}: "
                    f"missing {key} reference "
                    f"{reference!r}"
                )

    for key in scalar_reference_keys:
        reference = test.get(key)
        if (
            reference is not None
            and (
                not isinstance(reference, str)
                or not (
                    manifest.parent
                    / reference
                ).is_file()
            )
        ):
            errors.append(
                f"{manifest.relative_to(root)}: "
                f"missing {key} reference "
                f"{reference!r}"
            )

    for index, result in enumerate(
        test.get("results", [])
    ):
        if not isinstance(result, dict):
            errors.append(
                f"{manifest.relative_to(root)}: "
                f"results[{index}] "
                "must be a mapping"
            )
            continue

        for key in result_reference_keys:
            reference = result.get(key)

            if (
                reference is not None
                and (
                    not isinstance(reference, str)
                    or not (
                        manifest.parent
                        / reference
                    ).is_file()
                )
            ):
                errors.append(
                    f"{manifest.relative_to(root)}: "
                    f"missing results[{index}]."
                    f"{key} reference "
                    f"{reference!r}"
                )

if errors:
    print(
        "Validation FAILED with "
        f"{len(errors)} error(s):"
    )
    for error in errors:
        print(f"ERROR: {error}")
    sys.exit(1)

print(
    "Validation PASSED: "
    f"{len(yaml_files)} YAML files, "
    f"{len(policy_dirs)} policies, "
    f"{len(manifests)} suites."
)
