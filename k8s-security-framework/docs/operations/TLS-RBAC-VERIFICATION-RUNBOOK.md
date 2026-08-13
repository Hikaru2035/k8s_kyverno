# Kyverno TLS và RBAC verification runbook

## TLS định kỳ

Không in `tls.key`. Chỉ giải mã certificate công khai:

```bash
kubectl -n kyverno get secret kyverno-svc.kyverno.svc.kyverno-tls-pair \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  openssl x509 -noout -subject -issuer -serial -dates -ext subjectAltName -fingerprint -sha256
```

Lặp lại cho cleanup certificate. Để verify chain và CA bundle, dùng thư mục tạm:

```bash
audit_dir=$(mktemp -d /tmp/kyverno-tls.XXXXXX)
kubectl -n kyverno get secret kyverno-svc.kyverno.svc.kyverno-tls-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > "$audit_dir/ca.pem"
kubectl -n kyverno get secret kyverno-svc.kyverno.svc.kyverno-tls-pair \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > "$audit_dir/tls.pem"
kubectl get validatingwebhookconfiguration kyverno-policy-validating-webhook-cfg \
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d > "$audit_dir/bundle.pem"
openssl verify -CAfile "$audit_dir/ca.pem" "$audit_dir/tls.pem"
cmp "$audit_dir/ca.pem" "$audit_dir/bundle.pem"
```

Pass khi chain OK, SAN chứa service DNS, certificate chưa hết hạn và CA bundle khớp. Cảnh báo tối thiểu trước 30/14/7 ngày. Sau rotation, kiểm tra mọi webhook, không chỉ một configuration.

## Mismatch test an toàn

Chỉ chạy trên cluster disposable. Không thay Secret certificate trước vì có thể làm controller không Ready và khó rollback. Quy trình:

1. Lưu nguyên YAML webhook và certificate fingerprints.
2. Đảm bảo có terminal rollback không phụ thuộc workload admission đang test.
3. Dùng một webhook/canary rule giới hạn vào namespace test, `failurePolicy: Fail`.
4. Patch `caBundle` của đúng webhook canary bằng CA giả.
5. Server-side dry-run một tài nguyên match: kỳ vọng `x509: certificate signed by unknown authority`/webhook call failure.
6. Dry-run tài nguyên không match: phải thành công.
7. Khôi phục ngay YAML gốc, chờ controller reconcile, kiểm tra CA match và request thành công.

Không patch webhook Kyverno production đang quản lý vì controller có thể tự reconcile, tạo race và mở rộng blast radius. Dùng admission audit logs để xác nhận lỗi; không chỉ dựa vào client output.

## RBAC least-privilege

Liệt kê quyền hiệu lực:

```bash
for controller in admission-controller background-controller cleanup-controller reports-controller; do
  kubectl auth can-i --list \
    --as="system:serviceaccount:kyverno:kyverno-$controller"
done
```

Forbidden probes không tạo tài nguyên:

```bash
subject=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i get secrets -n default --as="$subject"
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io --as="$subject"
kubectl auth can-i delete pods -n default --as="$subject"
```

Kỳ vọng `no`. Test này dùng SubjectAccessReview, không thực hiện hành động. Với tình huống forbidden runtime, chỉ thực hiện trong namespace test bằng một service account canary; không cố tình gỡ quyền của controller đang chạy trên cluster dùng chung.

## Generate permissions

Với mỗi generate policy, lập ma trận `apiGroup/resource/verbs/scope` rồi kiểm tra background service account:

```bash
subject=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i create networkpolicies.networking.k8s.io -n <target-namespace> --as="$subject"
kubectl auth can-i update networkpolicies.networking.k8s.io -n <target-namespace> --as="$subject"
kubectl auth can-i delete networkpolicies.networking.k8s.io -n <target-namespace> --as="$subject"
```

Nguyên tắc:

- Chỉ thêm resource/verb policy thực sự cần; tránh wildcard.
- Không cấp Secret, RBAC escalation (`bind`, `escalate`, impersonate), ClusterRoleBinding hoặc workload controller nếu use case không bắt buộc.
- Quyền generate là cluster-wide nếu ClusterRoleBinding không giới hạn namespace; policy match/exclude là guardrail logic, không thay thế RBAC boundary.
- Sau thay đổi chart/RBAC, chạy negative probes và một generate canary trong namespace test; xác nhận UpdateRequest thành công, owner/synchronize behavior và cleanup đúng kỳ vọng.

## Rotation awareness

Theo dõi đồng thời: thời hạn leaf/CA, resourceVersion của TLS Secret, fingerprint CA trong mọi webhook, controller restart/readiness, và apiserver metric/log `failed calling webhook`. Rotation chỉ được coi thành công khi Secret mới, mounted certificate phục vụ thực tế và `caBundle` mới đã hội tụ; cập nhật một trong ba chưa đủ.

