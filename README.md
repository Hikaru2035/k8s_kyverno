# Kubernetes Security Framework with Kyverno

Framework Policy-as-Code cho Kubernetes sử dụng Kyverno, được xây dựng nhằm chuẩn hóa và tự động hóa việc áp dụng các chính sách bảo mật trên cluster.

Framework hiện gồm 29 policy thuộc các nhóm Pod Security, Image Security, Resource Governance, Metadata và Network Security. Mỗi policy được thiết kế kèm bộ test Positive, Negative, Boundary và Exception để kiểm tra logic trước khi triển khai thực tế.

Dự án hướng tới quy trình đầy đủ từ xây dựng policy, CLI Unit Test, Integration/E2E Test đến Audit, Enforce, Monitoring và Rollback.

> Trạng thái: Đã hoàn thiện 29 policy và CLI Unit Test. Hiện chuyển sang giai đoạn Integration/E2E testing trên Kubernetes cluster.

## Repository paths

Run validation and rendering from the repository root:

```sh
make policy-validate
make policy-render-all
bash k8s-security-framework/tests/policies/check-coverage.sh
bash k8s-security-framework/tests/policies/profiles/run.sh baseline
bash k8s-security-framework/tests/policies/regression/run.sh
kyverno test k8s-security-framework/tests/e2e_env/production/tests/rendered --require-tests
```

Source policies, profiles, scripts, and templates are under `k8s-security-framework/`.
Rendered environment bundles and their runbooks are under `k8s-security-framework/tests/e2e_env/`.
Helm configuration is under `helm/kyverno/` and `helm/harbor/`; monitoring resources are under `monitoring/`; Cosign keys are under `image-security/cosign/`.
CLI evidence is written under `artifacts/cli-unit/` and E2E evidence under `artifacts/e2e/`.
CI validation, rendering, regression, integration, and aggregate reports retain their named subdirectories under repository-root `artifacts/`.

See [the layout audit](docs/repository-layout-audit.md) for path mappings and verification results.

## Jenkins migration

Two independent pipelines are available: [framework CI](Jenkinsfile.ci) and
[secure application delivery](Jenkinsfile.delivery). See the
[Jenkins runbook](jenkins/README.md) for agents, credentials, job setup, evidence,
and the Harbor registry policy conflict that currently blocks Restricted delivery.
[Jenkins Helm preflight](helm/jenkins/README.md) renders and evaluates the official
chart before installation. No cluster installation is performed by repository setup.

**Keep `.gitlab-ci.yml` until Jenkins Pipeline 1 has demonstrated equivalent CI
coverage**, including all 29 CLI suites, rendered policy tests and Kind admission.
