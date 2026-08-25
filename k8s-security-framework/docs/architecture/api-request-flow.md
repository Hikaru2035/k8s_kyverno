# Kubernetes API Request Flow

## 1. Mục đích

Tài liệu này mô tả luồng xử lý một Kubernetes API request từ khi người dùng hoặc một Kubernetes component gửi request tới `kube-apiserver` cho đến khi resource được chấp nhận và lưu vào `etcd`.

Mục tiêu của tài liệu:

* Hiểu vai trò trung tâm của `kube-apiserver`.
* Phân biệt Authentication, Authorization và Admission Control.
* Hiểu RBAC nằm ở đâu trong request flow.
* Xác định chính xác vị trí Kyverno tham gia.
* Làm cơ sở cho việc xây dựng, test và troubleshooting Kyverno policy.
* Làm cơ sở phân tích các failure case liên quan đến Admission Webhook.

---

## 2. Tổng quan Request Flow

Ví dụ người dùng thực hiện:

```bash
kubectl apply -f deployment.yaml
```

Luồng tổng quát:

```text
kubectl / Client
       |
       | HTTPS :6443
       v
+----------------------+
|    kube-apiserver    |
+----------------------+
       |
       v
Authentication
       |
       v
Authorization
       |
       v
Admission Control
       |
       +-----------------------+
       |                       |
       v                       v
Mutating Admission      Validating Admission
       |                       |
       +-----------+-----------+
                   |
                   v
           Object Validation
                   |
                   v
                  etcd
                   |
                   v
           Resource Persisted
```

Trong Kubernetes, API Server là điểm trung tâm xử lý hầu hết các thao tác quản lý cluster.

Các thành phần khác như:

* `kubectl`
* kubelet
* scheduler
* controller-manager
* external controllers

đều tương tác với Kubernetes thông qua API Server thay vì sửa trực tiếp dữ liệu trong `etcd`.

---

## 3. API Server trong Kubernetes Lab

Kubernetes lab hiện tại sử dụng:

```text
Control Plane:
192.168.101.80

Kubernetes API:
https://192.168.101.80:6443
```

API Server được cấu hình với:

```text
--authorization-mode=Node,RBAC
--client-ca-file=/etc/kubernetes/pki/ca.crt
--tls-cert-file=/etc/kubernetes/pki/apiserver.crt
--tls-private-key-file=/etc/kubernetes/pki/apiserver.key
```

Vai trò chính của API Server:

* Cung cấp Kubernetes REST API.
* Xác thực client.
* Kiểm tra quyền truy cập.
* Thực hiện Admission Control.
* Validate Kubernetes object.
* Đọc và ghi cluster state thông qua `etcd`.

---

## 4. Client Request

Một request có thể đến từ:

* `kubectl`.
* kubelet.
* controller.
* scheduler.
* ServiceAccount.
* CI/CD pipeline.
* Kubernetes operator.
* External system gọi Kubernetes API.

Ví dụ:

```bash
kubectl create deployment nginx --image=nginx:1.29
```

`kubectl` sử dụng kubeconfig để biết:

* API Server endpoint.
* Cluster CA.
* User identity.
* Client certificate hoặc token.
* Current context.

Ví dụ kubeconfig của administrator trong lab:

```text
~/.kube/config
```

File này phải được bảo vệ vì chứa thông tin cho phép truy cập Kubernetes API.

---

## 5. TLS Connection

Client kết nối tới:

```text
https://192.168.101.80:6443
```

thông qua TLS.

TLS có hai mục tiêu chính:

* Bảo vệ dữ liệu truyền giữa client và API Server.
* Cho phép client xác minh API Server.

API Server sử dụng:

```text
/etc/kubernetes/pki/apiserver.crt
/etc/kubernetes/pki/apiserver.key
```

và Kubernetes CA:

```text
/etc/kubernetes/pki/ca.crt
```

Security requirement:

* Private key không được commit vào Git.
* `admin.conf` không được public.
* Kubeconfig phải có permission hạn chế.
* API Server không nên được expose trực tiếp ra Internet nếu không có network control thích hợp.

---

## 6. Authentication

Authentication trả lời câu hỏi:

```text
Who are you?
```

Kubernetes cần xác định identity của client trước khi xử lý quyền.

Các identity thường gặp:

* User.
* ServiceAccount.
* Kubelet.
* Node.
* Kubernetes component.
* Bootstrap identity.

Ví dụ ServiceAccount đã được dùng trong lab:

```text
system:serviceaccount:rbac-test:developer
```

Identity này bao gồm:

```text
Namespace:
rbac-test

ServiceAccount:
developer
```

Authentication chỉ xác định người gửi request.

Authentication không quyết định người đó được phép làm gì.

---

## 7. Node Authentication

Kubelet trên worker node cũng phải có identity.

Trong quá trình:

```text
kubeadm join
```

worker sử dụng:

* bootstrap token;
* Kubernetes CA hash;

để xác minh cluster và gửi Certificate Signing Request.

Luồng:

```text
Worker Node
     |
     | Bootstrap Token
     | CA Hash
     v
kube-apiserver
     |
     v
CSR
     |
     v
Approved / Issued
     |
     v
Kubelet Certificate
```

Sau khi join thành công, kubelet sử dụng certificate riêng để giao tiếp với API Server.

Bootstrap token chỉ phục vụ giai đoạn bootstrap và nên được revoke khi không còn cần thiết.

---

## 8. Authorization

Sau Authentication là Authorization.

Authorization trả lời câu hỏi:

```text
Are you allowed to do this?
```

Cluster hiện tại sử dụng:

```text
Node
RBAC
```

theo cấu hình:

```text
--authorization-mode=Node,RBAC
```

RBAC là cơ chế authorization chính được sử dụng để quản lý quyền của user và ServiceAccount.

---

## 9. RBAC

RBAC gồm bốn loại resource chính:

```text
Role
ClusterRole
RoleBinding
ClusterRoleBinding
```

### Role

Quyền trong một namespace.

Ví dụ:

```text
developer-role
```

có thể cho phép:

* get Pods.
* list Pods.
* create Deployment.

trong namespace cụ thể.

### ClusterRole

Quyền có thể áp dụng ở phạm vi cluster hoặc được bind vào namespace.

Ví dụ:

```text
view
cluster-admin
```

### RoleBinding

Gán Role hoặc ClusterRole cho identity trong một namespace.

### ClusterRoleBinding

Gán ClusterRole ở phạm vi cluster.

---

## 10. RBAC Baseline Test

Lab đã tạo:

```text
ServiceAccount:
developer

Namespace:
rbac-test
```

Kết quả kiểm thử:

```text
get pods trong rbac-test
-> ALLOW

create deployments trong rbac-test
-> ALLOW

get secrets trong rbac-test
-> DENY

get pods trong kube-system
-> DENY

create clusterroles
-> DENY
```

Kết quả trên chứng minh:

* Namespace isolation hoạt động.
* Developer chỉ có quyền cần thiết.
* Developer không thể đọc Secret.
* Developer không có cluster-level administrative privilege.

Đây là ví dụ của nguyên tắc:

```text
Least Privilege
```

---

## 11. Authentication và Authorization khác nhau như thế nào?

Ví dụ:

```text
developer muốn tạo Deployment
```

Authentication xử lý:

```text
Ai đang gửi request?

-> developer
```

Authorization xử lý:

```text
developer có quyền create Deployment không?

-> yes hoặc no
```

Luồng:

```text
Request
   |
   v
Authentication
   |
   | Identity = developer
   v
Authorization
   |
   | Permission check
   v
ALLOW / DENY
```

Nếu Authorization trả về `DENY`, request kết thúc tại đây.

Request không đi đến Admission Control.

---

## 12. Admission Control

Nếu request đã vượt qua Authentication và Authorization, request tiếp tục tới Admission Control.

Admission trả lời một câu hỏi khác:

```text
Identity có quyền thực hiện thao tác này,
nhưng resource này có được phép tồn tại hay không?
```

Ví dụ developer có quyền:

```text
create pods
```

RBAC có thể trả:

```text
ALLOW
```

nhưng Pod gửi lên có:

```yaml
securityContext:
  privileged: true
```

Security policy có thể quyết định:

```text
DENY
```

Do đó:

```text
RBAC ALLOW
không đồng nghĩa
Policy ALLOW
```

---

## 13. Admission Control trong Kubernetes

Admission Controller hoạt động sau:

```text
Authentication
Authorization
```

và trước:

```text
Persistence vào etcd
```

Có hai nhóm admission operation quan trọng:

```text
Mutating Admission
Validating Admission
```

---

## 14. Mutating Admission

Mutating Admission có thể thay đổi resource trước khi resource được lưu.

Ví dụ resource ban đầu:

```yaml
metadata:
  labels:
    app: nginx
```

Mutation có thể bổ sung:

```yaml
metadata:
  labels:
    managed-by: kyverno
```

Object sau mutation:

```yaml
metadata:
  labels:
    app: nginx
    managed-by: kyverno
```

Mutation thường được sử dụng để:

* thêm label;
* thêm annotation;
* inject giá trị mặc định;
* bổ sung security configuration;
* chuẩn hóa resource.

Kyverno hỗ trợ Mutation Policy.

---

## 15. Validating Admission

Validating Admission kiểm tra object có đáp ứng rule hay không.

Ví dụ:

```yaml
securityContext:
  privileged: true
```

Policy:

```text
KSV002 - Disallow Privileged
```

Nếu policy chạy ở Enforce mode:

```text
privileged=true
        |
        v
Validation
        |
        v
DENY
```

Object sẽ không được tạo.

---

## 16. Object Validation

Ngoài Admission Policy, API Server còn kiểm tra resource có hợp lệ với Kubernetes API schema hay không.

Ví dụ:

* field sai tên;
* type sai;
* required field thiếu;
* API version không hợp lệ.

Một resource có thể vượt qua policy nhưng vẫn bị Kubernetes API validation từ chối nếu manifest không hợp lệ.

---

## 17. Persistence vào etcd

Sau khi request vượt qua:

```text
Authentication
Authorization
Admission
Object Validation
```

resource mới được lưu vào `etcd`.

Luồng:

```text
API Server
    |
    v
etcd
```

Trong lab hiện tại:

```text
etcd
-> control-plane
-> 192.168.101.80
```

User và workload không nên sửa trực tiếp dữ liệu etcd.

Kubernetes resource phải được quản lý thông qua API Server.

---

## 18. Reconciliation sau Persistence

Sau khi desired state được lưu vào etcd, các controller bắt đầu reconciliation.

Ví dụ Deployment:

```text
Deployment
    |
    v
ReplicaSet
    |
    v
Pod
```

Scheduler tìm Pod chưa có node:

```text
Pod
  |
  v
Scheduler
  |
  v
Selected Node
```

Kubelet trên node sau đó yêu cầu container runtime chạy container.

Luồng đơn giản:

```text
API Server
   |
   v
Scheduler / Controller
   |
   v
API Server
   |
   v
Kubelet
   |
   v
containerd
   |
   v
Container
```

---

## 19. Kyverno nằm ở đâu?

Kyverno không thay thế API Server.

Kyverno không thay thế Authentication.

Kyverno không thay thế RBAC.

Kyverno chủ yếu hoạt động tại Admission layer.

Sau khi cài Kyverno:

```text
kubectl
   |
   v
kube-apiserver
   |
   v
Authentication
   |
   v
Authorization / RBAC
   |
   v
Admission
   |
   +----------------------------+
   |                            |
   | AdmissionReview HTTPS      |
   v                            |
Kyverno Admission Webhook       |
   |                            |
   v                            |
Policy Evaluation               |
   |                            |
   +-------------+--------------+
                 |
         Allow / Deny / Mutate
                 |
                 v
            kube-apiserver
                 |
                 v
                etcd
```

---

## 20. AdmissionReview

Kubernetes API Server gửi Admission Request tới external admission webhook theo cấu trúc `AdmissionReview`.

AdmissionReview chứa thông tin như:

* resource kind;
* namespace;
* operation;
* user information;
* object mới;
* object cũ khi update;
* request UID.

Kyverno đọc dữ liệu này để đánh giá policy.

Sau khi đánh giá, Kyverno trả response.

Response có thể:

```text
allowed = true
```

hoặc:

```text
allowed = false
```

Nếu mutation được thực hiện, response cũng có thể chứa patch.

---

## 21. Admission Webhook Registration

API Server biết phải gọi Kyverno nhờ các Kubernetes resource như:

```text
ValidatingWebhookConfiguration
MutatingWebhookConfiguration
```

Các resource này mô tả:

* webhook name;
* Service;
* namespace;
* path;
* CA bundle;
* resource rules;
* operation;
* selector;
* timeout;
* failure policy.

Sau khi cài Kyverno, các resource này phải được kiểm tra trong phase Kyverno Platform.

---

## 22. API Server tới Kyverno

Communication dự kiến:

```text
kube-apiserver
      |
      | HTTPS
      v
Kyverno Service
      |
      v
Kyverno Admission Controller
```

TLS được sử dụng để bảo vệ communication.

API Server phải trust certificate của Kyverno webhook.

---

## 23. TLS trong Admission Path

Kyverno webhook cần:

* TLS certificate;
* private key;
* CA trust.

Nếu TLS hoạt động:

```text
API Server
    |
    | trusted HTTPS
    v
Kyverno
```

Nếu TLS sai:

```text
API Server
    |
    X
    |
Kyverno
```

Request có thể bị lỗi admission.

Các lỗi phải kiểm thử sau này:

* certificate invalid;
* CA bundle mismatch;
* certificate expired;
* webhook Service không reachable.

---

## 24. RBAC và Kyverno khác nhau

RBAC trả lời:

```text
WHO can do WHAT?
```

Ví dụ:

```text
developer có được tạo Pod không?
```

Kyverno trả lời:

```text
WHAT resource configuration is allowed?
```

Ví dụ:

```text
Pod mà developer tạo có được privileged không?
```

Hai cơ chế hoạt động nối tiếp:

```text
Developer
    |
    v
Authentication
    |
    v
RBAC
"Can create Pod?"
    |
   YES
    |
    v
Kyverno
"Is this Pod compliant?"
    |
    +------ YES ------> Create
    |
    +------ NO -------> Deny
```

---

## 25. Baseline trước Kyverno

Trong Kubernetes lab hiện tại đã kiểm thử:

```yaml
securityContext:
  privileged: true
```

Kết quả:

```text
Pod Running
```

Luồng hiện tại:

```text
kubectl apply
      |
      v
API Server
      |
      v
Authentication
      |
      v
RBAC
      |
      v
Admission
      |
      v
ALLOW
      |
      v
Pod Running
```

Đây là baseline để so sánh sau khi Kyverno được triển khai.

---

## 26. Expected Flow sau khi có Policy

Ví dụ policy:

```text
KSV002 - Disallow Privileged
```

Luồng mong đợi:

```text
kubectl apply privileged-pod.yaml
        |
        v
kube-apiserver
        |
        v
Authentication
        |
        v
Authorization
        |
        v
Kyverno Webhook
        |
        v
KSV002
        |
        v
privileged == true
        |
        v
DENY
```

Resource không được lưu vào etcd.

---

## 27. Audit và Enforce

Policy có thể được triển khai theo lifecycle:

```text
Design
  |
  v
Test
  |
  v
Audit
  |
  v
Pilot
  |
  v
Enforce
```

Ở Audit:

```text
Violation
-> Resource vẫn có thể được tạo
-> Violation được ghi nhận
```

Ở Enforce:

```text
Violation
-> Request bị từ chối
```

Framework không nên đưa policy mới trực tiếp vào Enforce mà chưa có test và Audit observation.

---

## 28. Failure Scenario: Kyverno Down

Nếu API Server cần gọi Kyverno nhưng webhook không khả dụng:

```text
API Server
    |
    X
    |
Kyverno
```

Hành vi phụ thuộc vào webhook configuration, đặc biệt:

```text
failurePolicy
```

Hai định hướng chính:

```text
Fail
Ignore
```

Đây là trade-off giữa:

* Security.
* Availability.

Framework phải kiểm thử failure behavior thay vì chỉ dựa vào default configuration.

---

## 29. Failure Scenario: TLS Error

Các lỗi có thể gồm:

* certificate không hợp lệ;
* CA bundle sai;
* certificate expired;
* hostname mismatch;
* secret lỗi.

Ảnh hưởng:

```text
API Server không trust webhook
```

Kết quả có thể là admission error.

---

## 30. Failure Scenario: Network Error

API Server có thể không gọi được Kyverno khi:

* Service không có endpoint;
* Pod Kyverno down;
* DNS lỗi;
* networking lỗi;
* NetworkPolicy block traffic;
* webhook port không reachable.

Đây là failure case bắt buộc trong Failure Test Report.

---

## 31. Failure Scenario: RBAC Error

Một số Kyverno controller cần permission để:

* đọc resource;
* tạo resource;
* cập nhật resource;
* tạo PolicyReport;
* thực hiện background scan;
* generate resource.

Nếu RBAC thiếu:

```text
Kyverno
   |
   v
API Server
   |
   v
403 Forbidden
```

Do đó Kyverno RBAC phải:

* đủ quyền để hoạt động;
* không cấp quyền vượt mức cần thiết.

---

## 32. Failure Scenario: Policy Error

Policy có thể có các lỗi:

* syntax sai;
* selector sai;
* match sai resource;
* exclude sai;
* condition sai;
* false positive;
* false negative.

Ảnh hưởng có thể rất lớn nếu policy chạy ở Enforce.

Do đó phải có:

```text
Policy validation
Automated tests
Regression tests
CI pipeline
Audit phase
```

trước production enforcement.

---

## 33. Security Controls theo Request Stage

| Request Stage     | Security Control                           |
| ----------------- | ------------------------------------------ |
| Client            | kubeconfig, certificate, token protection  |
| Transport         | TLS                                        |
| Authentication    | client cert, ServiceAccount, node identity |
| Authorization     | RBAC                                       |
| Admission         | PSA, Kyverno                               |
| Object Validation | Kubernetes API schema                      |
| Persistence       | etcd                                       |
| Runtime           | SecurityContext                            |
| Network           | CNI, NetworkPolicy                         |

---

## 34. Security Principles

Request path phải tuân theo:

* Least Privilege.
* Defense in Depth.
* Secure by Default.
* Audit before Enforce.
* No secrets in source control.
* Reproducible configuration.
* Explicit failure behavior.
* Policy-as-Code.
* Automated testing.
* Traceable exceptions.

---

## 35. Kubernetes Request Flow Summary

Luồng cuối cùng của framework:

```text
Client
  |
  | HTTPS
  v
kube-apiserver
  |
  v
Authentication
  |
  v
Authorization / RBAC
  |
  v
Admission Control
  |
  +--> Mutating Admission
  |
  +--> Validating Admission
  |
  +--> Kyverno Policy Evaluation
  |
  v
Object Validation
  |
  v
etcd
  |
  v
Controllers / Scheduler / Kubelet
  |
  v
Runtime
```

---

## 36. Kết luận

Các điểm cần nắm:

* API Server là trung tâm của Kubernetes control plane.
* Authentication xác định identity.
* Authorization/RBAC xác định quyền.
* Admission kiểm tra resource trước khi persistence.
* Kyverno tham gia chủ yếu tại Admission layer.
* Kyverno không thay thế RBAC.
* Admission webhook sử dụng HTTPS/TLS.
* Request bị deny ở Admission không được lưu vào etcd.
* Webhook failure có thể ảnh hưởng cả security và availability.
* Policy phải trải qua test, Audit và Pilot trước Enforce.
* Admission path phải được monitoring và failure testing trong các phase tiếp theo.

Tài liệu này là cơ sở cho phase tiếp theo: triển khai Kyverno, xác minh Admission Webhook và bắt đầu xây dựng Policy-as-Code.