# Executable E2E environments

`environments/` is the existing general configuration and parameter layer. This `e2e_env/` tree contains self-contained, executable bundles for real development, staging, and production clusters. Each environment has the same 18 scenario IDs and filenames, its own policy copies, evidence directory, expected-results matrix, exemption configuration, and ordered runbook.

Regenerate deterministically with `make policy-render-all` (or run `scripts/render-policies.sh` once per environment when `make` is unavailable) after `scripts/scaffold-e2e.py`.
