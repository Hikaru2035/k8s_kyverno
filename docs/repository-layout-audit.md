# Repository layout audit

## Scope and design

Path-only adaptation of the user-reorganized working tree. Preserve policy expressions, actions, IDs, profile membership, fixtures, test decisions, and rendered content. Keep framework-relative source resolution and change only paths that cross moved directory boundaries. Audit covered all repository files except private-key contents and Git internals; historical artifacts were inventoried but not rewritten.

Execution sequence: inventory and resolve references; reproduce Makefile/render failures; repair paths; run existing validation commands; compare protected-file hashes and rendered counts; search for obsolete references again.

## Findings and replacements

| Affected files | Previous path | Current path | Effect |
| --- | --- | --- | --- |
| Root Makefile | `./scripts/` | repository-resolved `k8s-security-framework/scripts/` | Path only; works through `make -f` from another directory |
| Renderer | framework `e2e_env/` | framework `tests/e2e_env/` | Output/config location only |
| CI commands, drift check, change rule | framework `e2e_env/` | framework `tests/e2e_env/` | Path only |
| Profile/regression shell runners | framework `artifacts/cli-unit/` | repository `artifacts/cli-unit/` | Report location only |
| JSON regression runner | framework `artifacts/policy-tests/` | repository `artifacts/cli-unit/policy-tests/` | Report location and displayed relative path only; JSON schema unchanged |
| Evidence collector, three runbooks | working-directory `artifacts/e2e/` or `evidence/` | repository `artifacts/e2e/` | Evidence location only |
| CI artifact writers, uploads, JUnit, aggregate report | framework `artifacts/` | repository `artifacts/` | Path only; retain existing category names |
| CI regression setup | creates CLI JUnit directory but writes regression directory | creates repository `artifacts/regression/` | Repairs report-directory mismatch |
| CI YAML scan | old `ci/`, `e2e_env/`, `kyverno/helm/`, `environments/` | framework `tests/`, `template/`; root `helm/`, `monitoring/`, `image-security/` | Scan paths only; include root versions and Harbor manifest for YAML syntax |
| Root .gitignore | framework `image-security/cosign/` | repository `image-security/cosign/` | Restores private-key ignore paths |
| README | no current-layout command guide | root commands and current directory locations | Documentation only |

Installation configuration now lives in `helm/kyverno/` and `helm/harbor/`; monitoring resources in `monitoring/`; Cosign assets in `image-security/cosign/`. No embedded local references in those files needed edits. `failure_test/` now lives under framework `tests/`; its only file is historical evidence, with no active references to repair. The architecture document is empty; no obsolete commands were found there.

## Files changed by this audit

- `.gitignore`
- `.gitlab-ci.yml`
- `Makefile`
- `README.md` (preserves the user's existing text)
- `k8s-security-framework/scripts/render-policies.py`
- `k8s-security-framework/scripts/evidence/collect-evidence.sh`
- `k8s-security-framework/tests/policies/profiles/run.sh`
- `k8s-security-framework/tests/policies/regression/run.sh`
- `k8s-security-framework/tests/policies/run-policy-regression.py`
- `k8s-security-framework/tests/e2e_env/development/RUNBOOK.md`
- `k8s-security-framework/tests/e2e_env/staging/RUNBOOK.md`
- `k8s-security-framework/tests/e2e_env/production/RUNBOOK.md`
- `docs/repository-layout-audit.md`

Validation also produces fresh reports under repository-root `artifacts/`. The user's pre-existing moves/deletions are preserved.

## Intentionally unchanged

- Framework-local `policies/`, `profiles/`, and script-root resolution remain valid.
- All 389 Kyverno test file references already resolve relative to their manifests, including production rendered tests.
- Runbook `policies/` and `tests/` commands remain relative to each environment directory, as explicitly instructed there.
- `policies.ksp.io/rendered-from` remains framework-relative to preserve rendered output byte-for-byte.
- `kyverno/kyverno` is a Helm chart identifier, not a repository path.
- Historical artifacts, including old paths and obsolete-policy evidence, are retained. No `KSP-RES-007` source or profile entry is added.
- Existing CI report categories (`validate`, `check-policy`, `rendered-policy-test`, `regression`, `integration-kind`, `report`) retain their names under root `artifacts/`.
- `REPORT_ROOT`, `ARTIFACT_ROOT`, and `--output-dir` overrides retain their caller-selected path semantics.
- The three runbooks reference absent `EXPECTED-RESULTS.md` files. No relocated counterpart exists; restoring that content requires a separate, expectation-preserving documentation task.

## Harbor manifest recommendation

`test-harbor.yaml` appears to be a manual/debug smoke test, not an official automated fixture: no original CI/test runner references it, and it pins `worker-node-2`, a Harbor endpoint/image digest, namespace, and credential name. Leave it where it is for this refactor. If retained as a documented manual fixture, recommended location: `k8s-security-framework/tests/e2e_env/manual/test-harbor.yaml`. Moving or parameterizing it is outside this change.

## Validation commands

```sh
make policy-validate policy-render-all
bash k8s-security-framework/tests/policies/check-coverage.sh
make -f /root/k8s_kyverno/Makefile -C /tmp policy-validate policy-render ENVIRONMENT=production
bash k8s-security-framework/tests/policies/profiles/run.sh baseline
bash k8s-security-framework/tests/policies/profiles/run.sh standard
bash k8s-security-framework/tests/policies/profiles/run.sh restricted
bash k8s-security-framework/tests/policies/regression/run.sh
python3 k8s-security-framework/tests/policies/run-policy-regression.py
kyverno test k8s-security-framework/policies/image-security/KSP-IMG-004/tests --remove-color --detailed-results --require-tests
```

Also execute the actual YAML `script` blocks (with artifact-directory setup) for CI `validate`, `unit`, `rendered-policy-test`, `regression`, `check-policy`, and `report`, using `CI_PROJECT_DIR` and `FRAMEWORK_ROOT`. Tool installation, credential setup, and cluster integration are not run. No CI job invokes Makefile targets; the applicable validation/render targets are exercised directly. Profile and standalone regression runners are exercised from `/tmp`.

Additional checks: parse all CI shell blocks with `bash -n`; compile Python sources without writing bytecode; resolve all manifest file references; compare SHA-256 hashes with the pre-edit working-tree snapshot; count rendered policies per directory; verify private-key ignore matches; search all active files for obsolete path forms.

## Verification results

Kyverno CLI version: **1.18.2**, matching the existing CI pin.

| Check | Result |
| --- | --- |
| Policy configuration | Baseline 13, Standard 27, Restricted 29 |
| Coverage | 29/29 policy suites |
| Render all environments | Each has common 1, baseline 12, standard 14, restricted 2 (29 total) |
| Protected-content comparison | 585 source/profile/fixture/rendered files byte-identical to the pre-edit working tree, including all 87 rendered policies |
| Test path resolution | 389/389 file references resolve |
| CI YAML/reference validation | 609 YAML files, 29 policies, 29 suites |
| Rendered-policy tests | 3 passed, 0 failed |
| Baseline profile runner | 13 suites passed, 0 failed/missing |
| Standard profile runner | 27 suites passed, 0 failed/missing |
| Restricted profile runner | 29 suites passed, 0 failed/missing |
| Standalone regression runner | 29 suites passed, 0 failed |
| CI unit job and JUnit | Final run exit 0; 29 suites, 386 passed, 0 failed; 29 valid XML reports with 386 cases |
| CI aggregate report | Local report script passed; repository-root artifact paths resolved |
| CI aggregate regression | 386 tests passed, 0 failed |
| JSON evidence runner | 29 suites, 386 passed, 0 failed; schema preserved |
| CI rendering/drift gate | Pass in a clean temporary Git snapshot; user working tree left untouched |
| Shell/Python syntax | Pass |
| Private-key ignore paths | Root Cosign and nested wrong-key paths match |
| Obsolete-path search | No obsolete active references; historical evidence and audit mappings excluded |
| Artifact placement | No `k8s-security-framework/artifacts/` directory created |

## Remaining manual checks and observed limitations

- Full GitLab execution (runner/container setup, credentials, artifact upload) and live Kind/Harbor/cluster integration remain manual checks. Local execution covered the existing non-cluster job scripts; it did not install components or modify a cluster.
- Initial sandbox runs failed seven image-signature decisions because registry connections were blocked. The same tests pass with network access; no expectations or policy logic were changed.
- One network-enabled CI unit run encountered a Kyverno SDK `imagedataloader` runtime panic, `fatal error: concurrent map writes`. Its separate JUnit invocation passed; subsequent full unit runs passed all 386 tests, and the final run has a persisted zero exit status. This is recorded as a tool-runtime observation, not repaired through policy or CI behavior changes.
- The existing drift gate detects uncommitted layout moves in the user's working tree. A clean temporary snapshot passed the unchanged gate; all rendered policy bytes also match the pre-edit snapshot. The repository moves must be included when committing the refactor.
- Missing runbook `EXPECTED-RESULTS.md` documents have no replacement location available in this repository.

Final validation resumed on 2026-09-16: rechecked policy/profile counts, rendered bytes, YAML/reference validation, rendered tests, obsolete references, and the complete unit job. Existing timestamped user artifacts were preserved.
