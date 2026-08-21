# Policy Test Runbook

## Scope

This runbook covers the Kyverno CLI tests under:

```text
policies/<group>/<POLICY-ID>/tests/
```

Each policy test folder follows `docs/architecture/naming-matrix.md` and contains:

- `kyverno-test.yaml`
- `positive.yaml`
- `negative.yaml`
- `boundary.yaml`
- `exception.yaml` when the policy supports exceptions

Some mutate and generate policies also include expected output files such as `positive-patched.yaml`, `boundary-patched.yaml`, `positive-generated.yaml`, and `boundary-generated.yaml`. Exception-enabled policies include `exception-resource.yaml` so `exception.yaml` can stay dedicated to `PolicyException`.

## Prerequisites

- Kyverno CLI compatible with the framework target version.
- Run commands from the repository root.
- Do not run `latest` CLI images; pin the Kyverno CLI version used for evidence.

Record the CLI version before testing:

```bash
kyverno version
```

## Run All Policy Tests

```bash
kyverno test policies
```

Run the reproducible regression wrapper to create JSON evidence containing the
verbatim CLI version, Git revision, command, complete output, and exit code:

```bash
KYVERNO_BIN=/path/to/kyverno tests/policies/run-policy-regression.py
```

The report is written to
`artifacts/policy-tests/kyverno-policy-regression-<date>.json`. The wrapper does
not enable `--registry`, so image references in unit fixtures are not pulled.

Expected outcome:

- PASS means every `kyverno-test.yaml` expected result matched the policy behavior.
- FAIL means at least one `policy`, `rule`, `kind`, or `resource` did not match the declared result.

## Run One Policy Test

```bash
kyverno test policies/pod-security/KSP-POD-001
```

Use this when investigating a failure from the full suite.

## Result Interpretation

For validate policies:

- `positive.yaml` should pass or skip for deny-style rules where no deny condition is triggered.
- `negative.yaml` should fail.
- `boundary.yaml` should pass or skip, depending on policy rule type.
- `exception-resource.yaml` with `exception.yaml` should skip when an exception is permitted.

For mutate policies:

- Positive and boundary resources should match the expected patched resource files.
- Non-matching namespace or resource kinds should skip.

For generate policies:

- Opted-in namespaces should match the expected generated resource files.
- Non-opted-in namespaces should skip.

For image verification:

- `KSP-IMG-004` uses the bootstrap placeholder key and `harbor.example.com`; production evidence must be rerun after replacing them with the approved trust anchor and registry.

## Evidence

Save command output using the evidence naming convention:

```bash
kyverno test policies > artifacts/policy-tests/kyverno-policy-test-2026-08-17.txt
```

A pass record must include:

- Kyverno CLI version.
- Git commit or branch name.
- Full `kyverno test policies` output.
- Any known skipped cases and the reason.

A fail record must include:

- Failing policy ID.
- Failing rule and resource name.
- Expected result from `kyverno-test.yaml`.
- Actual CLI output.
- Remediation owner and follow-up ticket.

The JSON regression report stores the full, unmodified command transcript in
the top-level `evidence` field. Consumers must parse the JSON string before
comparing it with terminal output because JSON escapes newlines and quotes.
