#!/usr/bin/env python3
"""Run all Kyverno CLI policy tests and preserve verbatim evidence as JSON."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "policy-tests"


def run(command):
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kyverno-bin",
        default=os.environ.get("KYVERNO_BIN", "kyverno"),
        help="Kyverno CLI binary (default: KYVERNO_BIN or kyverno from PATH)",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    version_code, version_output = run([args.kyverno_bin, "version"])
    if version_code != 0:
        raise SystemExit(f"Unable to run Kyverno CLI:\n{version_output}")

    branch_code, branch = run(["git", "branch", "--show-current"])
    commit_code, commit = run(["git", "rev-parse", "HEAD"])
    test_command = [
        args.kyverno_bin,
        "test",
        "policies",
        "--remove-color",
        "--detailed-results",
        "--require-tests",
    ]
    test_code, test_output = run(test_command)
    finished = dt.datetime.now(dt.timezone.utc)

    match = re.search(r"Test Summary: (\d+) tests passed and (\d+) tests failed", test_output)
    passed = int(match.group(1)) if match else None
    failed = int(match.group(2)) if match else None
    suite_count = sum(1 for _ in (ROOT / "policies").rglob("kyverno-test.yaml"))
    invocation = f"cd {shlex.quote(str(ROOT))}\n{shlex.join(test_command)}"
    evidence = (
        f"$ {args.kyverno_bin} version\n"
        f"{version_output}"
        f"\n$ git branch --show-current\n{branch}"
        f"\n$ git rev-parse HEAD\n{commit}"
        f"\n$ {invocation}\n{test_output}"
        f"\n[exit_code] {test_code}\n"
    )

    report = {
        "schemaVersion": 1,
        "testType": "kyverno-cli-policy-regression",
        "status": "passed" if test_code == 0 else "failed",
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "repository": {
            "branch": branch.strip() if branch_code == 0 else None,
            "commit": commit.strip() if commit_code == 0 else None,
        },
        "kyvernoVersion": version_output.strip(),
        "command": invocation,
        "summary": {
            "suites": suite_count,
            "passed": passed,
            "failed": failed,
            "exitCode": test_code,
        },
        "notes": [
            "The CLI registry flag is intentionally disabled; test image references are not pulled.",
            "KSP-IMG-004 uses the bootstrap trust key and must be rerun with the production trust anchor for release evidence.",
        ],
        "evidence": evidence,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"kyverno-policy-regression-{started.date().isoformat()}.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(output.relative_to(ROOT))
    return test_code


if __name__ == "__main__":
    raise SystemExit(main())
