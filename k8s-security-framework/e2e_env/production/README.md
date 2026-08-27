# Production E2E bundle

This directory is a self-contained executable bundle for one real `production` cluster. Copy this directory alone, then follow `RUNBOOK.md`; it has no symlinks or runtime dependencies on another environment directory.

`policies/common/` contains KSP-META-003. `baseline/` contains the 10 minimum-profile policies; `standard/` and `restricted/` contain only set-difference additions. Runtime actions are rendered from `policies.ksp.io/prod-mode`, never inferred from the profile. `platform-namespaces.yaml` documents the explicit, name-based exemptions; an application label cannot create an exemption.

The repository's existing `environments/` tree remains the general parameter/configuration layer. `e2e_env/` contains executable cluster-specific E2E bundles.
