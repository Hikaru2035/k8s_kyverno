# Version Matrix & Naming Convention

## 1. Purpose

This document is the single source of truth for:

- Technology versions.
- Kubernetes resource naming.
- Policy naming.
- Test naming.
- Report naming.
- Environment naming.
- Framework versioning.

---

# 2. Technology Version Matrix

| Component | Version | Status | Notes |
|---|---|---|---|
| Ubuntu Server | TBD | Planned | Kubernetes nodes |
| Kubernetes | TBD | Planned | Cluster version |
| kubeadm | TBD | Planned | Same Kubernetes minor version |
| kubelet | TBD | Planned | Same Kubernetes minor version |
| kubectl | TBD | Planned | Compatible with cluster |
| containerd | TBD | Planned | Container runtime |
| Calico | TBD | Planned | CNI / NetworkPolicy |
| Helm | TBD | Planned | Package manager |
| Kyverno | TBD | Planned | Policy engine |
| Kyverno CLI | TBD | Planned | Policy testing |
| Kind | TBD | Planned | CI integration cluster |
| Harbor | TBD | Planned | Private registry |
| Cosign | TBD | Planned | Image signing |
| Prometheus | TBD | Planned | Metrics |
| Grafana | TBD | Planned | Monitoring |

Không sử dụng `latest`.

Version phải được pin trước khi framework được release.

---

# 3. General Naming Rules

Tất cả tên Kubernetes resource:

- lowercase.
- dùng dấu `-`.
- không dùng `_`.
- không dùng khoảng trắng.
- tên phải thể hiện mục đích.
- tránh tên chung chung như `test`, `app1`, `server1`.

Format chung:

<component>-<purpose>

Ví dụ:

security-demo
kyverno
monitoring
default-deny
resource-quota

---

# 4. Node Naming

Format:

<role>-<number>

Control Plane:

control-plane

Worker:

worker-01
worker-02

Không sử dụng:

ubuntu1
server1
node-test

---

# 5. Namespace Naming

System:

kyverno
monitoring
harbor

Environment:

dev
staging
production

Testing:

security-test
policy-test
failure-test

---

# 6. Application Resource Naming

Deployment:

<app>

Ví dụ:

demo-api

Service:

<app>

Ví dụ:

demo-api

ConfigMap:

<app>-config

Ví dụ:

demo-api-config

Secret:

<app>-secret

Ví dụ:

demo-api-secret

ServiceAccount:

<app>-sa

Ví dụ:

demo-api-sa

---

# 7. RBAC Naming

Role:

<scope>-<purpose>-role

Ví dụ:

developer-workload-role

ClusterRole:

<purpose>-cluster-role

Ví dụ:

security-admin-cluster-role

RoleBinding:

<subject>-<purpose>-binding

Ví dụ:

developer-workload-binding

ClusterRoleBinding:

<subject>-<purpose>-cluster-binding

---

# 8. NetworkPolicy Naming

Format:

<action>-<purpose>

Ví dụ:

default-deny-ingress
default-deny-egress
allow-dns
allow-api-access

---

# 9. Policy ID Convention

Validation:

KSVxxx

Mutation:

KSMxxx

Generation:

KSGxxx

Image Security:

KSIxxx

Ví dụ:

KSV001
KSV002
KSM001
KSG001
KSI001

ID không được tái sử dụng sau khi policy bị deprecated.

---

# 10. Kyverno Policy Naming

Format:

<action>-<object>

Ví dụ:

require-run-as-non-root
disallow-privileged
disallow-latest-tag
require-resource-limits
restrict-image-registry
verify-signed-images

---

# 11. Policy File Naming

Format:

<POLICY-ID>-<policy-name>.yaml

Ví dụ:

KSV001-require-run-as-non-root.yaml
KSV002-disallow-privileged.yaml
KSI001-disallow-latest-tag.yaml
KSI002-restrict-image-registry.yaml

---

# 12. Test Naming

Mỗi policy có một thư mục riêng:

tests/policies/<POLICY-ID>/

Ví dụ:

tests/policies/KSV001/

Bao gồm:

kyverno-test.yaml
positive.yaml
negative.yaml
boundary.yaml
exception.yaml

Nếu policy không hỗ trợ exception thì không cần exception.yaml.

---

# 13. Failure Test Naming

Format:

Fxx-<failure-name>

Ví dụ:

F01-admission-controller-down
F02-webhook-unavailable
F03-tls-ca-mismatch
F04-rbac-permission-denied
F05-registry-unavailable

Evidence:

artifacts/failures/F01/
artifacts/failures/F02/

---

# 14. Security Profile Naming

Chỉ sử dụng:

baseline
standard
restricted

Không sử dụng biến thể như:

basic
normal
high-security

để tránh trùng nghĩa.

---

# 15. Environment Naming

Chỉ sử dụng:

development
staging
production

Tên rút gọn nếu cần:

dev
staging
prod

Trong source directory sử dụng tên đầy đủ:

environments/development/
environments/staging/
environments/production/

---

# 16. Report Naming

Format:

<NUMBER>-<report-name>.pdf

Ví dụ:

01-kubernetes-security-architecture.pdf
02-kyverno-architecture.pdf
03-policy-catalog.pdf
04-policy-test-report.pdf
05-image-security-test-report.pdf
06-failure-test-report.pdf
07-poc-report.pdf
08-final-research-report.pdf

---

# 17. Evidence Naming

Format:

<component>-<test>-<date>.<extension>

Ví dụ:

kyverno-health-2026-09-01.txt
networkpolicy-test-2026-09-10.txt
KSV001-negative-test-2026-09-20.txt

Không lưu secret hoặc credential trong evidence.

---

# 18. Git Branch Naming

Vì project chỉ có một developer:

main

là branch ổn định.

Khi cần branch riêng:

feature/<name>
fix/<name>
docs/<name>

Ví dụ:

feature/image-verification
fix/KSV003-boundary-test
docs/policy-catalog

---

# 19. Git Tag / Framework Version

Framework sử dụng Semantic Versioning:

vMAJOR.MINOR.PATCH

Development:

v0.1.0
v0.2.0
v0.3.0

Final PoC:

v1.0.0

PATCH:
Bug fix hoặc documentation nhỏ.

MINOR:
Thêm policy, test hoặc feature tương thích.

MAJOR:
Breaking change về policy behavior hoặc framework architecture.

---

# 20. Version Change Rule

Khi thay đổi version của component:

1. Kiểm tra compatibility.
2. Update Version Matrix.
3. Update installation/configuration nếu cần.
4. Re-run relevant tests.
5. Commit thay đổi.
6. Ghi version mới vào report nếu ảnh hưởng PoC.

---

# 21. Naming Change Rule

Không rename Policy ID đã được sử dụng.

Ví dụ:

KSV001

sau khi đã publish thì luôn là KSV001.

Nếu policy bị bỏ:

Status = Deprecated

Không dùng KSV001 cho policy khác.