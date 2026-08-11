# Kubernetes Security Architecture

## 1. Scope của Kubernetes Security Lab

Xây dựng một Kubernetes Security Lab bằng VMware để làm nền tảng cho toàn bộ đề tài Kyverno Security & Policy-as-Code.

Dự án không nhằm mô phỏng đầy đủ production, nhưng phải đủ để nghiên cứu, triển khai và kiểm thử:

- Kubernetes API Server.
- Authentication.
- Authorization và RBAC.
- Admission Controller.
- Admission Webhook.
- Container runtime.
- Kubernetes networking.
- NetworkPolicy.
- SecurityContext.
- Pod Security Standards.
- ServiceAccount.
- TLS/PKI.
- Helm.
- Kyverno ở phase tiếp theo.
- Policy testing.
- Failure testing.
- Image security.
- Monitoring.
- End-to-end PoC.

## 2. Mô hình cluster

Chạy trên VMware.

### Control Plane

- Hostname: `control-plane`
- IP: `192.168.101.80`
- Role: Control Plane
- CPU: 4 vCPU khuyến nghị
- RAM: 4-6 GB
- Disk: 40 GB
- OS: Ubuntu Server LTS

### Worker 01

- Hostname: `worker-01`
- IP: `192.168.101.81`
- Role: Worker
- CPU: 2 vCPU
- RAM: 4 GB
- Disk: 30-40 GB
- OS: Ubuntu Server LTS

### Worker 02

- Hostname: `worker-02`
- IP: `192.168.101.82`
- Role: Worker
- CPU: 2 vCPU
- RAM: 3-4 GB
- Disk: 30-40 GB
- OS: Ubuntu Server LTS

## 3. Network Plan

### VMware / Node Network

- CIDR: `192.168.101.0/24`
- Control Plane: `192.168.101.80`
- Worker 01: `192.168.101.81`
- Worker 02: `192.168.101.82`

### Pod Network

- CIDR dự kiến: `10.244.0.0/16`
- CNI: Calico

### Service Network

- CIDR: `10.96.0.0/12`

Ba dải Node Network, Pod Network và Service Network không overlap.

## 4. Kubernetes Components

- kube-apiserver.
- etcd.
- kube-scheduler.
- kube-controller-manager.
- kubelet.
- containerd.
- CoreDNS.
- CNI plugin.

## 5. Các kết nối chính

- `kubectl -> HTTPS TCP/6443 -> kube-apiserver`
- Worker -> kube-apiserver.
- kube-apiserver -> kubelet qua TCP/10250.
- kube-apiserver -> etcd.
- Phase sau: `kube-apiserver -> Admission Webhook -> Kyverno Service -> Kyverno Admission Controller`.

## 6. Port Matrix cơ bản

| Port | Protocol | Component | Mục đích |
|---|---|---|---|
| 22 | TCP | SSH | Quản trị VM |
| 6443 | TCP | kube-apiserver | Kubernetes API |
| 2379-2380 | TCP | etcd | etcd client/server |
| 10250 | TCP | kubelet | Kubelet API |
| 10257 | TCP | controller-manager | Secure controller-manager |
| 10259 | TCP | scheduler | Secure scheduler |
| 30000-32767 | TCP/UDP | NodePort | Chỉ mở nếu cần test NodePort |

Không expose trực tiếp các cổng control-plane ra Internet.

## 7. Advance Security Requirements

- API Server không public Internet.
- Chỉ admin workstation và node cần thiết được truy cập.
- Sử dụng TLS.
- Không commit kubeconfig, admin.conf, private key, token, TLS key, `.env`, registry credentials.
- Áp dụng least privilege RBAC.

## 8. RBAC Baseline

| Role | Workload | Policy | RBAC | Scope |
|---|---|---|---|---|
| cluster-admin | Full | Full | Full | Cluster |
| security-admin | Read/Manage security | Full | Limited | Cluster |
| developer | CRUD workload | No | No | Namespace |
| viewer | Read | Read | Read | Read-only |

Bài test bắt buộc:

- Developer tạo Deployment được.
- Developer không tạo ClusterRole được.
- Viewer không sửa Deployment được.
- Security admin quản lý policy được ở phase Kyverno.

## 9. SecurityContext Baseline

Các field phải nghiên cứu và có workload test:

- `runAsNonRoot`
- `runAsUser`
- `privileged`
- `allowPrivilegeEscalation`
- `capabilities`
- `readOnlyRootFilesystem`
- `seccompProfile`

## 10. Pod Security Standards

Phải nắm ba mức Privileged, Baseline và Restricted.

Trong project, PSS dùng làm baseline/reference; Kyverno là policy engine chính cho Policy-as-Code.

## 11. NetworkPolicy Baseline

Phải chứng minh:

- Pod A gọi Pod B khi chưa có policy: PASS.
- Apply NetworkPolicy chặn traffic: DENY.
- DNS vẫn hoạt động nếu egress policy được cấu hình đúng.

## 12. Definition of Done Phase 2

Phase 2 chỉ hoàn thành khi:

### Cluster

- Control Plane `Ready`.
- Worker 01 `Ready`.
- Worker 02 `Ready`, hoặc lý do giảm còn một worker được ghi rõ.

### Runtime

- containerd running.
- `SystemdCgroup=true`.
- swap disabled.

### Kubernetes Core

- kube-apiserver healthy.
- scheduler healthy.
- controller-manager healthy.
- etcd healthy.
- kubelet healthy.
- CoreDNS Running.

### Networking

- Node-to-Node PASS.
- Pod-to-Pod PASS.
- Pod-to-Service PASS.
- DNS PASS.
- NetworkPolicy enforcement PASS.

### Authentication/RBAC

- kubeconfig hoạt động.
- TLS trust hoạt động.
- cluster-admin test PASS.
- developer test PASS.
- viewer test PASS.
- unauthorized action bị DENY.

### Security

- SecurityContext test hoàn tất.
- PSS Baseline/Restricted được document.
- Có workload an toàn và workload vi phạm để dùng cho phase policy.

## Phase 2 Exit Criteria

Milestone: `M1 - Kubernetes Security Lab Ready`