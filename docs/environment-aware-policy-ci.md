# Environment-aware Policy CI

The implementation follows the user-supplied test responsibility contract:
source CLI suites retain their complete logic expectations; rendered CI verifies
offline evaluation and environment admission configuration; runtime scenarios
remain owned by E2E/Delivery. No missing EXPECTED-RESULTS documents are invented.

## Implementation plan

1. Add regression tests for all environments, case classification, action-aware
   admission expectations, disabled mutations, inventory integrity, and packaging.
2. Centralize the rendered adapter around source manifests and rendered policy
   data. Keep every canonical resource assertion identifiable. Include existing
   selected-environment offline regression manifests separately.
3. Replace fixed policy pass counts with exact case-plan reconciliation and
   separate policy, CLI-case, and configuration-assertion coverage. Only POD-012
   disabled admission and IMG-004 external verification authorize exemptions.
4. Render the selected environment once, retain a render receipt, verify source
   inputs and tested bytes during packaging, and publish one environment artifact.
5. Wire the Jenkins choice through the scripts; retain the source CLI gate and
   leave Delivery unchanged. Run real offline CLI tests plus negative regressions
   and print comparisons, inventories, metadata, and diffs.

## CLI semantics

The pinned Kyverno 1.18.2 `test` command compares expected policy evaluation
results, not HTTP admission responses. A violating Audit/Warn policy still has
an expected evaluation result of `fail`. Rendered evidence records this result
separately from the admission disposition derived from verified validationActions.
The development/staging IMG-001 probe confirms this with the real CLI. Do not
change a negative evaluation expectation to `pass` just because admission allows
the request. See https://kyverno.io/docs/subprojects/kyverno-cli/ and
https://kyverno.io/docs/policy-types/validating-policy/.

Disabled POD-012 admission is checked structurally; source mutation assertions
remain owned by CLI Unit and are explicitly non-applicable to rendered admission.
Runtime inventories are ownership records, never skipped rendered assertions.

## Verification risks

Reject missing/duplicate/substituted cases and policies, unknown environments,
unrecognized exemption reasons, unexpected CLI exclusions, changed test inputs,
cross-environment attestations, and policy or evidence byte changes. Packaging
must not invoke the renderer or modify policy YAML.
