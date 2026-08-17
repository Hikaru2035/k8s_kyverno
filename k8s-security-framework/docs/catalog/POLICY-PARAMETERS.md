# Policy Parameter Specification

## 1. Mục tiêu và nguyên tắc

Parameter là dữ liệu vận hành, không phải logic policy. Base policy chỉ định rule; profile chọn control; environment cung cấp giá trị. Một giá trị chỉ có một nguồn chính thức trong `environments/<environment>/parameters.env`.

Nguyên tắc:

- Không dùng `latest`, wildcard registry hoặc private key trong Git.
- Production không được render nếu còn `harbor.example.com` hoặc bootstrap Cosign key.
- Danh sách dùng dấu phẩy, không có khoảng trắng. Label key phải là DNS-qualified key.
- Thay đổi parameter phải qua review, render diff và regression test như thay đổi policy.
- Secret/private key nằm trong secret manager; repository chỉ giữ đường dẫn public key hoặc public certificate.

## 2. Parameter schema

| Key | Type | Required | Validation | Consumer |
|---|---|---:|---|---|
| `ENVIRONMENT` | enum | yes | `development|staging|production` | labels/render path |
| `PROFILE` | enum | yes | `baseline|standard|restricted` | policy selection |
| `APPROVED_REGISTRIES` | CSV hostname | yes | không scheme, tag hoặc wildcard root | KSP-IMG-002 |
| `SIGNED_IMAGE_PATTERNS` | CSV glob | restricted prod | phải thuộc approved registry | KSP-IMG-004 |
| `COSIGN_PUBLIC_KEY_FILE` | relative path | restricted prod | PEM public key, không private key | KSP-IMG-004 |
| `OWNER_LABEL_KEY` | label key | yes | DNS-qualified | KSP-META-002 |
| `ENVIRONMENT_LABEL_KEY` | label key | yes | DNS-qualified | KSP-META-003 |
| `EXCLUDED_NAMESPACES` | CSV | yes | system namespaces explicit | render selectors/exclusions |
| `QUOTA_REQUESTS_CPU` | quantity | generate | Kubernetes CPU quantity | KSP-RES-005 |
| `QUOTA_REQUESTS_MEMORY` | quantity | generate | Kubernetes memory quantity | KSP-RES-005 |
| `QUOTA_LIMITS_CPU` | quantity | generate | >= request | KSP-RES-005 |
| `QUOTA_LIMITS_MEMORY` | quantity | generate | >= request | KSP-RES-005 |
| `QUOTA_PODS` | integer | generate | > 0 | KSP-RES-005 |
| `LIMIT_DEFAULT_*` | quantity | generate | >= default request | KSP-RES-006 |
| `LIMIT_MIN_*` | quantity | generate | <= default request | KSP-RES-006 |
| `LIMIT_MAX_*` | quantity | generate | >= default | KSP-RES-006 |
| `WEBHOOK_TIMEOUT_SECONDS` | integer | yes | 1–30 | policy webhook config |
| `VERIFY_IMAGE_TIMEOUT_SECONDS` | integer | yes | 1–30 | KSP-IMG-004 |
| `FAILURE_POLICY_CRITICAL` | enum | yes | `Fail|Ignore` | critical policies |
| `FAILURE_POLICY_DEFAULT` | enum | yes | `Fail|Ignore` | non-critical policies |
| `AUDIT_MIN_DAYS` | integer | yes | >= 1 | promotion gate |
| `MAX_VIOLATION_RATE` | decimal | yes | 0–1 | promotion gate |
| `MAX_FALSE_POSITIVE_RATE` | decimal | yes | 0–1 | promotion gate |
| `MAX_EXCEPTION_RATE` | decimal | yes | 0–1 | promotion gate |
| `MAX_ADMISSION_P95_MS` | integer | yes | > 0 | SLO/promotion gate |
| `MAX_WEBHOOK_ERROR_RATE` | decimal | yes | 0–1 | rollback gate |

## 3. Registry và signing

Production Restricted chỉ chấp nhận registry tổ chức và image reference theo digest. Signature verification phải dùng public key thật hoặc keyless identity được phê duyệt. `COSIGN_PUBLIC_KEY_FILE` không được trỏ tới file chứa `PRIVATE KEY`.

Registry bootstrap trong base policy chỉ phục vụ development. Renderer production phải fail trước khi tạo artifact nếu placeholder còn tồn tại.

## 4. Labels

Canonical keys:

```text
app.kubernetes.io/name
app.kubernetes.io/managed-by
policies.ksp.io/owner
policies.ksp.io/environment
policies.ksp.io/governed
```

Owner không bao giờ được mutate tự động. Environment chỉ nhận `dev`, `staging`, `production`. Thay label key là breaking change vì ảnh hưởng inventory, exception và report query.

## 5. Excluded namespaces

Mặc định loại khỏi workload policy: `kube-system,kube-public,kube-node-lease,kyverno`. Không loại namespace ứng dụng chỉ để giảm violation. Exception workload phải có owner, lý do, expiry và ticket.

Generate/mutate dùng opt-in namespace label; validate/verify dùng exclusion tập trung khi render. Namespace exclusion là security boundary và cần security approval.

## 6. Resource defaults

Giá trị trong environment file là bootstrap ceiling, không thay capacity planning. Điều kiện bắt buộc:

```text
min <= defaultRequest <= default <= max
quota requests <= quota limits
```

Production phải review sizing theo namespace class trước khi bật generate synchronization vì thay parameter có thể overwrite generated resources.

## 7. Threshold ownership

Platform team sở hữu latency/error thresholds; Security team sở hữu violation/false-positive/exception thresholds; application owner chịu remediation. Thay threshold không được dùng để hợp thức hóa regression đang tồn tại.

## 8. Validation và thay đổi

```bash
./scripts/validate-policy-config.sh
./scripts/render-policies.sh development
./scripts/render-policies.sh staging
./scripts/render-policies.sh production
```

Artifact render phải được lưu trong CI, diff với release trước và server-side dry-run trên cluster test trước merge.
