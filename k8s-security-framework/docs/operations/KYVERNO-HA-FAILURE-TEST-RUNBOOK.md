# Kyverno HA và failure-test runbook

Runbook này áp dụng cho chart 3.8.2/Kyverno v1.18.2 trong repository. Luôn dùng một terminal thứ hai có quyền cluster-admin làm kênh rollback.

## 1. Render và áp dụng baseline

Từ thư mục `k8s-security-framework`:

```bash
helm template kyverno kyverno/helm/kyverno-3.8.2.tgz \
  --namespace kyverno \
  -f kyverno/helm/values-staging.yaml > /tmp/kyverno-staging-rendered.yaml

helm upgrade --install kyverno kyverno/helm/kyverno-3.8.2.tgz \
  --namespace kyverno \
  -f kyverno/helm/values-staging.yaml \
  --wait --timeout 15m
```

Nếu chart path cục bộ khác, dùng đúng package/chart mà script cài đặt của dự án tham chiếu. Trước upgrade, kiểm tra image đã pull được trên cả ba node; lần cài ngày 2026-08-12 từng timeout do registry connection reset.

## 2. Acceptance gate trước failure test

```bash
helm status kyverno -n kyverno
kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=5m
kubectl -n kyverno get deploy,pod,pdb -o wide
kubectl -n kyverno get endpointslice \
  -l kubernetes.io/service-name=kyverno-svc -o wide
kubectl -n kyverno get deploy kyverno-admission-controller \
  -o jsonpath='{.spec.replicas}{" replicas\n"}{.spec.template.spec.topologySpreadConstraints}{"\n"}{.spec.template.spec.affinity}{"\n"}'
```

Điều kiện bắt buộc:

- Admission `3/3 Ready`, endpoint count = 3.
- Pod admission phân bố trên các node; không có hai pod cùng failure domain nếu topology cho phép.
- PDB admission có `minAvailable: 2`; `disruptionsAllowed` phải phù hợp khi cả ba pod healthy.
- Resources và rolling update trùng staging values.
- Một canary policy đã tạo resource webhook; server-side dry-run của tài nguyên hợp lệ thành công và tài nguyên vi phạm bị deny/audit đúng thiết kế.

Lưu ý: PDB chỉ bảo vệ voluntary eviction; nó không ngăn node crash, process crash, `kubectl delete pod`, hoặc việc scale deployment xuống.

## 3. Test mất một admission replica

Ghi nhận baseline trước:

```bash
kubectl -n kyverno get pod -l app.kubernetes.io/component=admission-controller -o wide
kubectl -n kyverno get endpointslice -l kubernetes.io/service-name=kyverno-svc -o yaml
kubectl get --raw='/readyz?verbose'
```

Chọn đúng **một** pod admission và xóa pod đó. Đây là hành động phá vỡ có kiểm soát, chỉ chạy sau acceptance gate:

```bash
kubectl -n kyverno delete pod <one-admission-pod>
```

Trong khi pod được thay thế, liên tục chạy workload canary bằng `--dry-run=server`, đồng thời quan sát endpoint và latency/error của apiserver. Pass khi:

- Admission request không bị gián đoạn ngoài ngưỡng SLO.
- Service luôn còn ít nhất 2 endpoint Ready.
- Deployment tự phục hồi về 3/3 và pod mới được phân bố đúng.
- Không có `failed calling webhook`, TLS error hoặc timeout bất thường trong events/logs.

Nếu endpoint giảm dưới 2, dừng test tổng thể, chờ rollout hồi phục và điều tra scheduling/readiness.

## 4. Test voluntary disruption/PDB

Dùng `kubectl drain` chỉ khi đã xác nhận node mục tiêu và có phương án uncordon. PDB phải ngăn eviction khiến admission xuống dưới 2 available. Không dùng `--disable-eviction` hoặc force để lách PDB trong test baseline.

Pass khi drain hoặc eviction thứ hai bị chặn đúng lúc, trong khi admission vẫn phục vụ. Sau test:

```bash
kubectl uncordon <node>
kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=5m
```

## 5. Total failure và failurePolicy

Không scale admission về 0 trên cluster dùng chung. Để kiểm chứng fail-closed/fail-open, tạo cluster test cô lập:

- Policy/resource webhook `failurePolicy: Fail`: request match phải thất bại khi endpoint không reachable.
- Webhook `failurePolicy: Ignore`: request match phải tiếp tục và audit log phải thể hiện webhook failure.
- Request không match rules/selector không bị ảnh hưởng.

Trước test cần lưu YAML webhook, Service, EndpointSlice và có terminal rollback. Khôi phục controller trước; chỉ sửa failurePolicy như break-glass cuối cùng, có phê duyệt và audit trail.

## 6. Controller failure matrix

| Test | Kỳ vọng |
|---|---|
| Dừng leader background | Replica khác nhận leader; generate/background scan trễ ngắn, admission không gián đoạn |
| Dừng reports leader | Report tạm trễ rồi hội tụ; enforcement không đổi |
| Dừng cleanup leader | Cleanup/TTL trễ rồi hội tụ; không xóa sai/đúp tài nguyên |
| Mất một node | Admission còn endpoint trên failure domain khác; PDB không bảo vệ node crash nên topology mới là lớp bảo vệ chính |

Sau mỗi test, kiểm tra leader election/reconcile logs, backlog UpdateRequest/report, endpoint count và thời gian hội tụ; hoàn tất một test và phục hồi hoàn toàn trước test tiếp theo.

