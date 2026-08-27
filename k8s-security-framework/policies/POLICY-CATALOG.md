# Base policy catalog

Catalog này chứa 30 Kyverno CEL policy source: 1 common/bootstrap governance policy và 29 security policies.

- Mỗi Policy ID có đúng một thư mục và một file theo format `<POLICY-ID>-<policy-name>.yaml`.
- Validate/verify policy mặc định chạy `Audit`; promotion sang `Enforce` được thực hiện bởi profile/overlay theo annotation `policies.ksp.io/*-mode`.
- Mutate/generate policy chỉ áp dụng lên namespace opt-in bằng label để không tác động namespace hệ thống ngoài ý muốn.
- Các rule Pod bao phủ Pod trực tiếp và Pod template của Deployment, StatefulSet, DaemonSet, Job, CronJob thông qua Kyverno autogen.
- Public key trong KSP-IMG-004 chỉ là bootstrap placeholder. Phải thay bằng trust anchor do dự án quản lý trước khi bật Enforce.
- Catalog target Kyverno v1.18.2/chart 3.8.2 và dùng schema `policies.kyverno.io/v1` (`ValidatingPolicy`, `MutatingPolicy`, `GeneratingPolicy`, `ImageValidatingPolicy`).

| Group | Directory | Count |
|---|---|---:|
| Pod Security | `pod-security/` | 14 |
| Image Security | `image-security/` | 4 |
| Resource Governance | `resource-governance/` | 7 |
| Metadata | `metadata/` | 4 |
| Network Security | `network-security/` | 1 |
| **Total** | | **30** |

Namespace activation labels:

```yaml
policies.ksp.io/mutate-default-security-context: "enabled"
policies.ksp.io/generate-resource-governance: "enabled"
policies.ksp.io/generate-network-baseline: "enabled"
```

Operational labels used by generated resources and metadata mutation:

```yaml
app.kubernetes.io/managed-by: kyverno
ksp.io/environment: dev|staging|production
ksp.io/profile: baseline|standard|restricted
policies.ksp.io/quota-class: small|medium|large
```

Governance dependency:

```text
KSP-RES-007 validates opted-in Namespace labels
  -> KSP-RES-005 consumes environment + quota-class
  -> KSP-RES-006 consumes environment
```

`KSP-IMG-004: DEFERRED - registry/signing integration not available in current phase`.
