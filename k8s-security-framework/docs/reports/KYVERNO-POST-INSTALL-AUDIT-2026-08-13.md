# Báo cáo kiểm tra Kyverno sau cài đặt

Ngày kiểm tra: 2026-08-13 UTC  
Cluster context: `kubernetes-admin@kubernetes`  
Kubernetes: v1.35.7, 3 node Ready  
Kyverno: chart 3.8.2, app v1.18.2

## Kết luận nhanh

Kyverno đã được upgrade bằng `kyverno/helm/values-staging.yaml` và **đạt HA baseline đã định nghĩa trong repository**. Single-admission-replica failure test đã PASS. Baseline vẫn chỉ chịu được lỗi một admission replica; ba admission pod hiện phân bố trên hai worker node, không phải ba failure domain độc lập.

| Hạng mục | Trạng thái | Kết luận |
|---|---|---|
| Pod/controller health | PASS | Admission `3/3`; Background/Cleanup/Reports đều `2/2`, tất cả pod Running và không restart sau upgrade |
| Webhook → Service → endpoint | PASS | `kyverno-svc:443` trỏ tới 3 admission endpoint Ready trên port `9443` |
| TLS chain và CA bundle | PASS | Cả admission và cleanup leaf certificate verify OK; CA trong Secret trùng byte với `caBundle` |
| Admission server-side dry-run | PASS có giới hạn | Dry-run Namespace và ConfigMap thành công; hiện không có policy tài nguyên nên chưa chứng minh đường validate/mutate policy workload |
| HA staging | PASS có giới hạn | Runtime đúng 3/2/2/2, đủ PDB/resources/topology/rolling strategy; admission chỉ trải trên 2 worker node |
| Helm release | PASS | Revision 5, trạng thái `deployed`, mô tả `Upgrade complete` |
| RBAC forbidden checks | PASS | Các SA bị từ chối đọc/tạo Secret, xóa Pod, tạo ClusterRoleBinding và tạo Deployment trong các phép thử đã chạy |
| Generate permissions | REVIEW | Background SA có quyền ghi ConfigMap, quota, limit, NetworkPolicy, Ingress, Role/RoleBinding và ResourceClaim; đây là blast radius có chủ đích nhưng rộng |
| TLS mismatch destructive test | NOT RUN | Không làm hỏng `caBundle` trên cluster đang dùng; runbook riêng cung cấp test cô lập và rollback |
| Single-replica failure test | PASS | Xóa một admission pod; luôn còn 2 endpoint Ready, 6/6 dry-run thành công, tự phục hồi 3/3 sau khoảng 15 giây |

## 1. Admission webhook tới kube-apiserver

Luồng thực tế:

```text
kube-apiserver
  -> ValidatingWebhookConfiguration / MutatingWebhookConfiguration
  -> clientConfig.service: kyverno/kyverno-svc:443
  -> Service targetPort 9443
  -> 3 endpoint Ready trên port 9443
  -> 3 admission-controller pod trên worker-node-1 và worker-node-2
```

Cleanup webhook dùng `kyverno/kyverno-cleanup-controller:443` → `10.244.19.133:9443` trên worker-node-2.

Các cấu hình webhook được phát hiện:

- Policy validation/mutation và validation của exception/global-context/cleanup dùng `failurePolicy: Fail`, timeout 10 giây. Nếu service không có endpoint, request thuộc rules của chúng sẽ bị từ chối sau timeout/lỗi kết nối.
- TTL validation và verify-mutating webhook dùng `failurePolicy: Ignore`; khi controller lỗi, request tiếp tục nhưng chức năng kiểm tra tương ứng bị bỏ qua.
- `kyverno-resource-validating-webhook-cfg` và `kyverno-resource-mutating-webhook-cfg` hiện có 0 webhook vì cluster không có `ClusterPolicy`/`Policy`. Do đó dry-run workload thành công chủ yếu chứng minh API server hoạt động, không phải một policy workload đã được Kyverno đánh giá.
- Namespace `kube-system` bị loại theo Helm computed values; namespace `kyverno` cũng được loại qua resource filters. Đây là lựa chọn operability, đồng thời tạo vùng không được policy workload bảo vệ.

Blast radius của outage admission phụ thuộc `rules` và `failurePolicy`, không phải mọi request trong cluster đều mặc nhiên bị chặn. Với cấu hình hiện tại, quản trị policy/exception/global context/cleanup policy là nhóm fail-closed rõ nhất; khi resource webhooks được Kyverno sinh ra từ policy, blast radius sẽ mở rộng theo match rules của policy đó.

## 2. Controller, RBAC và hành vi khi lỗi

| Controller | Quyền/chức năng chính quan sát được | Khi lỗi | Blast radius |
|---|---|---|---|
| Admission | Quản lý webhook config và policy CRs; nhận admission; tạo report tạm | Webhook `Fail` chặn request match; `Ignore` cho qua | Đường ghi API theo rules đang đăng ký |
| Background | Scan/generate; ghi UpdateRequest; có quyền ghi một tập tài nguyên generate | Generate/synchronize và background scan dừng/trễ; admission validation vẫn có thể chạy | Tất cả namespace cho resource được cấp quyền generate |
| Reports | Đọc workload/policy và ghi ephemeral/policy/open reports | Enforcement admission không dừng, nhưng compliance report cũ/trễ | Visibility/audit toàn cluster |
| Cleanup | Đọc cleanup/deleting policy; xử lý xóa qua SubjectAccessReview; quản lý cleanup validating webhook | Cleanup/TTL trễ; validation cleanup policy `Fail` có thể chặn sửa policy | Tài nguyên match cleanup policy và quản trị cleanup policy |

Kiểm tra `kubectl auth can-i` cho từng service account xác nhận các quyền nhạy cảm sau đều trả `no`: đọc/tạo Secret ở `default`, xóa Pod ở `default`, tạo ClusterRoleBinding, tạo Deployment. Riêng background SA trả `yes` cho tạo NetworkPolicy, phù hợp cấu hình generate permissions trong computed Helm values.

Nhận xét least privilege:

- Không phát hiện quyền tạo ClusterRoleBinding hoặc đọc Secret trong test có mục tiêu.
- Admission và Reports ClusterRole hiển thị nhiều CRUD trên Kyverno/report CRDs; cần thiết cho controller nhưng phải coi controller compromise là quyền sửa trạng thái/chính sách Kyverno ở phạm vi cluster.
- Background controller được cấp thêm quyền ghi nhiều loại tài nguyên. Chỉ giữ loại tài nguyên thực sự được policy generate sử dụng; mỗi lần thêm generate kind phải review `extraResources` và chạy `can-i` lại.
- `kubectl auth can-i --list` là kiểm tra hiệu lực tổng hợp, không phải chứng minh tối thiểu tuyệt đối. Review định kỳ ClusterRole/Binding và audit log vẫn cần thiết.

## 3. HA baseline production-like — kiểm chứng sau upgrade

Desired state trong `values-staging.yaml`:

- Admission: 3 replicas, PDB `minAvailable: 2`, rolling update `maxUnavailable: 0`, topology spread theo hostname, request 200m/256Mi, limit 1 CPU/768Mi.
- Background/Cleanup/Reports: mỗi controller 2 replicas, PDB `minAvailable: 1`, có requests/limits.

### Kết quả runtime lúc 05:41–05:53 UTC

| Acceptance criterion | Kết quả | Trạng thái |
|---|---|---|
| Helm release | Revision 5, `deployed`, `Upgrade complete` | PASS |
| Replica topology | Admission 3/3; Background 2/2; Cleanup 2/2; Reports 2/2 | PASS |
| Admission endpoint | 3/3 EndpointSlice endpoint Ready trên port 9443 | PASS |
| Admission PDB | `minAvailable: 2`, `disruptionsAllowed: 1` khi healthy | PASS |
| Controller PDB | Background/Cleanup/Reports `minAvailable: 1`, mỗi PDB cho phép 1 disruption khi healthy | PASS |
| Rolling update | `maxSurge: 1`, `maxUnavailable: 0` | PASS |
| Admission resources | request 200m/256Mi; limit 1 CPU/768Mi | PASS |
| Topology spread | `maxSkew: 1`, key hostname, `ScheduleAnyway` | PASS theo values |
| API Priority and Fairness | FlowSchema/PriorityLevel cho Admission và Reports tồn tại, `MISSINGPL=False` | PASS |
| Failure policy | Webhook quản trị chính dùng `Fail`; TTL/monitor dùng `Ignore`; resource webhook chưa có rules vì chưa có policy | PASS theo thiết kế hiện tại |

Phân bố sau failure test là hai admission pod trên `worker-node-1` và một pod trên `worker-node-2`. Cluster có ba node nhưng control-plane không schedule workload, nên chỉ có hai failure domain khả dụng. `ScheduleAnyway` là soft constraint: cấu hình đạt đúng staging values nhưng không bảo đảm một pod trên mỗi node. Mất toàn bộ worker node đang chứa hai pod có thể tạm làm admission giảm còn một replica; nếu cần chịu lỗi một worker node mà vẫn giữ tối thiểu hai admission replica, cần thêm worker/failure domain và cân nhắc `DoNotSchedule` cùng capacity phù hợp.

Pod anti-affinity mặc định vẫn là `preferred` với weight 1. Lớp phân tán chính của baseline hiện là topology spread soft constraint. PDB chỉ chi phối voluntary eviction, không ngăn `kubectl delete pod`, node crash hoặc scale-down.

### Single-admission-replica failure test

Thời gian: 2026-08-13 05:52:39–05:53:05 UTC.

1. Acceptance gate trước test: admission `3/3`, 3 endpoint Ready, PDB `minAvailable: 2` và `disruptionsAllowed: 1`.
2. Xóa pod `kyverno-admission-controller-5858b456df-c69jp` trên `worker-node-2` bằng `--wait=false`.
3. Trong ba mẫu đầu, deployment còn `2 Ready/2 Available`; EndpointSlice giữ hai endpoint Ready, endpoint thay thế tồn tại nhưng `ready=false`.
4. Gửi sáu ConfigMap admission request bằng `--dry-run=server`, cách nhau khoảng 5 giây; cả 6/6 thành công.
5. Sau khoảng 15 giây, pod thay thế Ready; deployment và EndpointSlice trở lại 3/3. Snapshot cuối: tất cả controller đạt desired replicas, không restart.

Kết luận: **PASS cho lỗi một admission pod**. Không quan sát gián đoạn admission trong probe. Phép thử không chứng minh enforcement của workload policy vì resource webhook vẫn chưa có rules, và không thay thế các test voluntary eviction/PDB, mất toàn bộ node hoặc total admission outage.

## 4. TLS certificate, Secret và CA bundle

| Endpoint | Leaf validity | SAN | CA validity | Trust |
|---|---|---|---|---|
| `kyverno-svc.kyverno.svc` | 2026-08-12 → 2027-01-09 | service short name, namespace name, `.svc` FQDN | đến 2027-08-12 | verify OK; `caBundle` MATCH |
| `kyverno-cleanup-controller.kyverno.svc` | 2026-08-12 → 2027-01-09 | service short name, namespace name, `.svc` FQDN | đến 2027-08-12 | verify OK; `caBundle` MATCH |

Leaf certificate có thời hạn khoảng 150 ngày, CA khoảng một năm. Chart đang tự quản lý certificate (`certManager.enabled: false`). Cần cảnh báo trước 30/14/7 ngày và quan sát cả Secret lẫn mọi webhook `caBundle` sau restart/upgrade/rotation. Chỉ certificate metadata và SHA-256 fingerprint được đọc; không xuất private key.

Mismatch test không được chạy trực tiếp vì sửa `caBundle` của webhook `Fail` có thể chặn API writes. Cách test an toàn và rollback được mô tả trong `TLS-RBAC-VERIFICATION-RUNBOOK.md`.

## 5. Hành động ưu tiên

1. Tạo ít nhất một policy audit/enforce canary để chứng minh resource webhook thật sự được đăng ký và request bị Kyverno đánh giá trong failure test.
2. Nếu yêu cầu chịu lỗi một worker node mà vẫn còn ít nhất hai admission replica, bổ sung worker/failure domain và đánh giá đổi topology constraint sang `DoNotSchedule`.
3. Chạy voluntary eviction test để kiểm chứng PDB; không chạy total outage/mismatch trên production-like cluster khi chưa có break-glass và rollback terminal riêng.
4. Thu hẹp `backgroundController.rbac.coreClusterRole.extraResources` theo catalog generate policy thực tế.
5. Thiết lập cảnh báo certificate expiry, webhook rejection/latency, endpoint count và controller leader/reconcile errors.

## Bằng chứng/lệnh đã chạy

Đợt kiểm tra ban đầu dùng các lệnh chỉ đọc hoặc `--dry-run=server`: `helm list/status/get values`, `kubectl get` nodes/deployments/pods/services/endpoints/PDB/webhooks/events/policies, `kubectl auth can-i`, đọc certificate công khai từ Secret, `openssl x509/verify/cmp`, và dry-run Namespace/ConfigMap.

Đợt kiểm chứng HA sau upgrade đọc Helm revision 5, Deployment/PDB/EndpointSlice/FlowSchema/webhook runtime và thực hiện đúng một thay đổi có kiểm soát: xóa một admission pod để Deployment tự tái tạo. Không tạo Namespace/ConfigMap thật, không scale controller, không patch webhook/Secret/failurePolicy và không chạy total outage test.
