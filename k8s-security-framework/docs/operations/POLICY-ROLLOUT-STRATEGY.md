# Policy Rollout and Enforcement Strategy

## 1. Lifecycle bắt buộc

```text
Draft → Test → Audit → Violation analysis → Remediation
      → Pilot → Enforce → Monitor → Rollback/Steady state
```

Không được bỏ qua stage đối với policy mới hoặc semantic change. Parameter-only change vẫn phải chạy Test, Pilot và Monitor nếu ảnh hưởng match, generate, registry, quota hoặc failure behavior.

## 2. Evidence và trách nhiệm

| Stage | Owner | Evidence bắt buộc | Promote khi |
|---|---|---|---|
| Draft | Policy author | ID, threat/risk, scope, remediation, exception model | peer review; không hard-code/placeholder ngoài development |
| Test | Policy author + QA | schema validation, positive/negative/boundary/exception tests | 100% test pass; không critical/high false negative đã biết |
| Audit | Platform + Security | PolicyReport, admission latency/error baseline | đủ `AUDIT_MIN_DAYS`; sample đại diện workload/namespace |
| Violation analysis | Security + app owners | phân loại true/false positive, owner, due date | false-positive và exception rate dưới threshold |
| Remediation | App owner | fixed manifests/images, approved temporary exceptions | critical violation = 0 trong pilot scope; high có kế hoạch được duyệt |
| Pilot | Platform | namespace allowlist, rollback artifact, on-call, dashboards | ít nhất 7 ngày hoặc 2 release cycle; SLO đạt; không Sev-1/2 |
| Enforce | Security approver + change manager | signed approval, render diff, server dry-run | toàn bộ gate đạt; rollback tested |
| Monitor | Platform/SOC | alert dashboard, rejection/report trend | ổn định qua 24h high-risk và 7 ngày normal window |
| Rollback | Incident commander/change owner | incident/ticket, artifact version, post-check | admission và workload SLO phục hồi |

## 3. Promotion criteria định lượng

Tất cả điều kiện phải đúng:

- Test pass 100%; server-side dry-run pass trên đúng Kyverno/Kubernetes target.
- Audit duration >= `AUDIT_MIN_DAYS`.
- Violation rate <= `MAX_VIOLATION_RATE` trong phạm vi promotion.
- False-positive rate <= `MAX_FALSE_POSITIVE_RATE`.
- Active exception rate <= `MAX_EXCEPTION_RATE`; không exception hết hạn.
- Critical violation chưa remediation = 0 trong pilot scope.
- Admission p95 <= `MAX_ADMISSION_P95_MS` và webhook error rate <= `MAX_WEBHOOK_ERROR_RATE`.
- Không tăng API server admission timeout/rejection ngoài error budget.
- Generate/mutate idempotent; dry-run/render diff không có resource ngoài scope.
- Có artifact trước/sau, lệnh rollback, on-call và maintenance/change record.

Threshold lấy từ `environments/<environment>/parameters.env`; không sửa threshold trong cùng change để làm promotion pass.

## 4. Pilot design

- Chọn namespace đại diện nhưng blast radius giới hạn; không bắt đầu bằng system hoặc highest-revenue workload.
- Enforce bằng selector/overlay pilot, không sửa base policy cho toàn cluster.
- Với default-deny network, apply DNS và application allow policies trước; health check ingress/egress ngay sau change.
- Với verifyImages, xác minh registry availability, credential helper, trust key và signed test image trước.
- Với quota/LimitRange, kiểm tra object count và resource headroom trước `synchronize`.

## 5. Rollback triggers

Rollback ngay khi có một trong các điều kiện:

- Webhook error rate vượt threshold trong 5 phút hoặc admission p95 vượt 2× threshold trong 10 phút.
- API write quan trọng bị chặn sai, false positive critical/high, hoặc Sev-1/2.
- Workload availability/SLO giảm do mutation, quota, network hoặc image verification.
- Controller endpoint giảm dưới HA minimum trong lúc policy fail-closed gây ảnh hưởng.
- Generate loop, overwrite ngoài dự kiến, report backlog tăng không kiểm soát.
- Exception khẩn cấp cần wildcard hoặc không có expiry/owner.

## 6. Rollback order

Ưu tiên thay đổi nhỏ nhất có thể phục hồi dịch vụ:

1. Dừng promotion/pipeline và giữ evidence.
2. Chuyển policy gây lỗi từ Enforce về Audit bằng artifact đã review; không xóa toàn bộ catalog.
3. Tắt selector pilot hoặc restore parameter/render artifact trước đó.
4. Với mutate/generate, ngừng rule trước; đánh giá generated/mutated resources trước khi cleanup.
5. Chỉ dùng `failurePolicy: Ignore` như break-glass khi Kyverno/webhook outage thực sự chặn API và có incident commander phê duyệt.
6. Xác nhận admission, workload SLO và report trở lại baseline; mở post-incident review.

Không rollback bằng cách xóa webhook configuration do Kyverno quản lý. Không xóa NetworkPolicy/ResourceQuota hàng loạt khi chưa xác định owner và tác động.

## 7. Severity và fail-closed production

- Critical policy: `failureAction: Enforce` sau gate và `failurePolicy: Fail`.
- High policy: Audit → pilot → Enforce; fail-closed sau promotion.
- Medium/Low: Audit mặc định; Enforce khi risk owner chứng minh lợi ích và compatibility.
- VerifyImages Critical: chỉ Enforce khi production trust anchor tồn tại và registry path đã test.
- Trong outage, failure policy và enforcement action là hai control khác nhau; rollback phải ghi rõ control nào thay đổi.

## 8. Change record checklist

```text
Policy IDs/profile/environment:
Base and rendered artifact commit/digest:
Test report:
Audit window and violation counts:
False-positive/exception rates:
Pilot scope and dates:
Admission latency/error before/after:
Approvers:
Rollback artifact/command:
Monitoring owner/window:
```

