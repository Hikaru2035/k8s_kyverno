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

Không sử dụng `latest`. Version phải được pin trước khi framework được release.

---

# 4. Node Naming
Format:

<role>-<number>

Control Plane: control-plane
Worker: worker-node-01; worker-node-02
Không sử dụng: ubuntu1 server1; node-test

---

# 5. Namespace Naming
System: kyverno; monitoring; harbor
Environment: dev; staging; production
Testing: security-test; policy-test; failure-test

---

# 6. Application Resource Naming
Deployment, Service:

<app>

Example: demo-api

ConfigMap:

<app>-config

Example: demo-api-config

Secret:

<app>-secret

Example: demo-api-secret

ServiceAccount:

<app>-sa

Example:demo-api-sa

---

# 7. RBAC Naming
Role:

<scope>-<purpose>-role

Example: developer-workload-role

ClusterRole:

<purpose>-cluster-role

Example: security-admin-cluster-role

RoleBinding:

<subject>-<purpose>-binding

Example: developer-workload-binding

ClusterRoleBinding:

<subject>-<purpose>-cluster-binding

---

# 8. NetworkPolicy Naming
Format:

<action>-<purpose>

Example: default-deny-ingress; default-deny-egress; allow-dns; allow-api-access

---

# 10. Kyverno Policy Naming
Format:

<action>-<object>

Example: require-run-as-non-root; disallow-privileged; require-resource-limits

---

# 11. Policy File Naming
Format:

<POLICY-ID>-<policy-name>.yaml

Example: KSP-POD-001-require-run-as-non-root.yaml

---

# 12. Test Naming
Mỗi policy có một thư mục riêng:

policies/<POLICY-ID>/tests/

Example: policies/KSP-POD-001/tests

Bao gồm:
kyverno-test.yaml
positive.yaml
negative.yaml
boundary.yaml
exception.yaml (optional)

---

# 13. Failure Test Naming
Format:

Fxx-<failure-name>

Ví dụ: F01-admission-controller-down; F02-webhook-unavailable
Evidence: artifacts/failures/F01/

---

# 14. Security Profile Naming
Chỉ sử dụng: baseline; standard; restricted
Không sử dụng biến thể như: basic; normal; high-security
---

# 15. Environment Naming
Chỉ sử dụng: development; staging; production
Tên rút gọn nếu cần: dev; staging; prod
Trong source directory sử dụng tên đầy đủ

---

# 17. Evidence Naming
Format:

<component>-<test>-<date>.<extension>

Example: kyverno-health-2026-09-01.txt; networkpolicy-test-2026-09-10.txt; KSV001-negative-test-2026-09-20.txt

---

# 18. Git Branch Naming
main là branch ổn định.

---

# 19. Git Tag / Framework Version
Framework sử dụng Semantic Versioning: vMAJOR.MINOR.PATCH
Development: v0.1.0; v0.2.0; v0.3.0

Final PoC: v1.0.0

PATCH: Bug fix hoặc documentation nhỏ.
MINOR: Thêm policy, test hoặc feature tương thích.
MAJOR: Breaking change về policy behavior hoặc framework architecture.

---

# 20. Naming Change Rule
Không rename Policy ID đã được sử dụng.