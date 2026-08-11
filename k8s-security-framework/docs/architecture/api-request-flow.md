# Kubernetes API Request Flow

## 1. Mục tiêu

Mô tả luồng xử lý một Kubernetes API request từ lúc người dùng chạy `kubectl` đến khi trạng thái được ghi vào etcd.

## 2. Luồng tổng quát

`kubectl -> kube-apiserver -> Authentication -> Authorization -> Admission -> etcd`

Sau đó controller thực hiện reconciliation để đưa actual state về desired state.

## 3. Client Request

Ví dụ:

```bash
kubectl apply -f deployment.yaml
```

`kubectl` đọc kubeconfig để lấy API Server endpoint, CA certificate, client certificate/token, context và user.

Endpoint lab: `https://192.168.101.80:6443`

## 4. Authentication

API Server xác định người gọi là ai.

Các cơ chế cần nắm:

- Client certificate.
- ServiceAccount token.
- Bootstrap token.

Authentication trả lời: `Who are you?`

## 5. Authorization

Project sử dụng RBAC:

- Role.
- ClusterRole.
- RoleBinding.
- ClusterRoleBinding.

Authorization trả lời: `Are you allowed to do this?`

Ví dụ:

```bash
kubectl auth can-i create deployments
kubectl auth can-i create clusterroles
```

## 6. Admission

Sau Authentication và Authorization, request đi qua Admission gồm built-in Admission Controllers và Dynamic Admission Webhooks.

Kyverno ở phase sau hoạt động tại đây.

## 7. Persistence

Nếu request hợp lệ: `kube-apiserver -> etcd`.

Các component khác không truy cập etcd trực tiếp.

## 8. Reconciliation

Controller Manager quan sát state qua API Server.

Ví dụ: `Deployment -> ReplicaSet -> Pod`.

Scheduler chọn node; kubelet yêu cầu container runtime chạy container.

## 9. Security Control Mapping

| Stage | Security Control |
|---|---|
| Client | kubeconfig, certificate |
| Authentication | Client cert, ServiceAccount |
| Authorization | RBAC |
| Admission | PSA, Kyverno |
| Persistence | etcd |
| Runtime | SecurityContext, container runtime |
| Network | CNI, NetworkPolicy |

## 10. Phase 2 Verification

```bash
kubectl cluster-info
kubectl auth can-i get pods
kubectl auth can-i create deployments
kubectl get --raw=/readyz
```
