from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "policies"


DIGEST = "a" * 64
DIGEST_UPPER = "A" * 64


def docs(text: str) -> str:
    return text.strip() + "\n"


def pod(name, body="", namespace="policy-test", image="harbor.example.com/demo-api:1.0.0"):
    body = body.rstrip()
    if body:
        body = "\n" + indent(body, 2)
    return docs(f"""
apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {namespace}
spec:{body}
  containers:
    - name: demo-api
      image: {image}
""")


def pod_custom(name, spec, namespace="policy-test"):
    return docs(f"""
apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {namespace}
spec:
{indent(spec.rstrip(), 2)}
""")


def workload(kind, name, labels=None):
    labels = labels or {}
    label_text = "\n".join(f"    {k}: {v}" for k, v in labels.items())
    label_block = f"\n  labels:\n{label_text}" if labels else ""
    template_labels = labels.copy()
    template_labels.setdefault("app.kubernetes.io/name", "demo-api")
    pod_labels = "\n".join(f"        {k}: {v}" for k, v in template_labels.items())
    if kind == "CronJob":
        return docs(f"""
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {name}
  namespace: policy-test{label_block}
spec:
  schedule: "*/5 * * * *"
  jobTemplate:
    spec:
      template:
        metadata:
          labels:
{pod_labels}
        spec:
          restartPolicy: OnFailure
          containers:
            - name: demo-api
              image: harbor.example.com/demo-api:1.0.0
""")
    if kind == "Job":
        return docs(f"""
apiVersion: batch/v1
kind: Job
metadata:
  name: {name}
  namespace: policy-test{label_block}
spec:
  template:
    metadata:
      labels:
{pod_labels}
    spec:
      restartPolicy: Never
      containers:
        - name: demo-api
          image: harbor.example.com/demo-api:1.0.0
""")
    return docs(f"""
apiVersion: apps/v1
kind: {kind}
metadata:
  name: {name}
  namespace: policy-test{label_block}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: demo-api
  template:
    metadata:
      labels:
{pod_labels}
    spec:
      containers:
        - name: demo-api
          image: harbor.example.com/demo-api:1.0.0
""")


def namespace(name, labels=None):
    labels = labels or {}
    label_block = ""
    if labels:
        label_block = "\n  labels:\n" + "\n".join(f"    {k}: {v}" for k, v in labels.items())
    return docs(f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {name}{label_block}
""")


def indent(text, spaces):
    return "\n".join((" " * spaces) + line if line else line for line in text.splitlines())


def multi(*items):
    return "---\n".join(item.strip() + "\n" for item in items)


def exception(policy, rule, kind, name, namespace_name="policy-test"):
    return docs(f"""
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: {policy}-exception
  namespace: {namespace_name}
spec:
  exceptions:
    - policyName: {policy}
      ruleNames:
        - {rule}
  match:
    any:
      - resources:
          kinds:
            - {kind}
          names:
            - {name}
          namespaces:
            - {namespace_name}
""")


def positive_negative_boundary():
    good_digest = f"harbor.example.com/demo-api@sha256:{DIGEST}"
    return {
        "KSP-IMG-001": {
            "positive": pod("img-001-positive", image="harbor.example.com/demo-api:1.0.0"),
            "negative": multi(
                pod("img-001-negative-latest", image="harbor.example.com/demo-api:latest"),
                pod("img-001-negative-untagged", image="demo-api"),
            ),
            "boundary": pod("img-001-boundary-digest", image=good_digest),
            "negative_resources": ["img-001-negative-latest", "img-001-negative-untagged"],
            "positive_result": "skip",
            "boundary_result": "skip",
        },
        "KSP-IMG-002": {
            "positive": pod("img-002-positive", image="harbor.example.com/demo-api:1.0.0"),
            "negative": pod("img-002-negative", image="docker.io/library/nginx:1.25"),
            "boundary": pod("img-002-boundary", image="reg.kyverno.io/kyverno/kyverno:1.18.2"),
            "positive_result": "skip",
            "boundary_result": "skip",
        },
        "KSP-IMG-003": {
            "positive": pod("img-003-positive", image=good_digest),
            "negative": pod("img-003-negative", image="harbor.example.com/demo-api:1.0.0"),
            "boundary": pod("img-003-boundary-uppercase", image=f"harbor.example.com/demo-api@sha256:{DIGEST_UPPER}"),
            "positive_result": "skip",
            "boundary_result": "skip",
        },
        "KSP-IMG-004": {
            "positive": pod("img-004-positive-out-of-scope", image="registry.k8s.io/pause:3.10"),
            "negative": pod("img-004-negative-unsigned", image=good_digest),
            "boundary": pod("img-004-boundary-out-of-scope", image="reg.kyverno.io/kyverno/kyverno:1.18.2"),
            "positive_result": "skip",
            "boundary_result": "skip",
        },
        "KSP-POD-001": {
            "positive": pod_custom("pod-001-positive", "securityContext:\n  runAsNonRoot: true\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0"),
            "negative": pod("pod-001-negative"),
            "boundary": pod_custom("pod-001-boundary-containers", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      runAsNonRoot: true\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      runAsNonRoot: true"),
        },
        "KSP-POD-002": {
            "positive": pod_custom("pod-002-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      privileged: false"),
            "negative": pod_custom("pod-002-negative", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      privileged: true"),
            "boundary": pod("pod-002-boundary-omitted"),
        },
        "KSP-POD-003": {
            "positive": pod_custom("pod-003-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false"),
            "negative": pod_custom("pod-003-negative", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: true"),
            "boundary": pod_custom("pod-003-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false"),
        },
        "KSP-POD-004": {
            "positive": pod("pod-004-positive", "hostNetwork: false"),
            "negative": pod("pod-004-negative", "hostNetwork: true"),
            "boundary": pod("pod-004-boundary-unset"),
        },
        "KSP-POD-005": {
            "positive": pod("pod-005-positive", "hostPID: false"),
            "negative": pod("pod-005-negative", "hostPID: true"),
            "boundary": pod("pod-005-boundary-unset"),
        },
        "KSP-POD-006": {
            "positive": pod("pod-006-positive", "hostIPC: false"),
            "negative": pod("pod-006-negative", "hostIPC: true"),
            "boundary": pod("pod-006-boundary-unset"),
        },
        "KSP-POD-007": {
            "positive": pod_custom("pod-007-positive", "volumes:\n  - name: cache\n    emptyDir: {}\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    volumeMounts:\n      - name: cache\n        mountPath: /cache"),
            "negative": pod_custom("pod-007-negative", "volumes:\n  - name: host-root\n    hostPath:\n      path: /\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    volumeMounts:\n      - name: host-root\n        mountPath: /host"),
            "boundary": pod("pod-007-boundary-no-volumes"),
        },
        "KSP-POD-008": {
            "positive": pod_custom("pod-008-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      capabilities:\n        drop: [ALL]"),
            "negative": pod("pod-008-negative"),
            "boundary": pod_custom("pod-008-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      capabilities:\n        drop: [ALL]\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      capabilities:\n        drop: [ALL]"),
        },
        "KSP-POD-009": {
            "positive": pod_custom("pod-009-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      capabilities:\n        add: [NET_BIND_SERVICE]"),
            "negative": pod_custom("pod-009-negative", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      capabilities:\n        add: [SYS_ADMIN]"),
            "boundary": pod("pod-009-boundary-no-add"),
        },
        "KSP-POD-010": {
            "positive": pod_custom("pod-010-positive", "securityContext:\n  seccompProfile:\n    type: RuntimeDefault\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0"),
            "negative": pod_custom("pod-010-negative", "securityContext:\n  seccompProfile:\n    type: Unconfined\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0"),
            "boundary": pod_custom("pod-010-boundary-localhost", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      seccompProfile:\n        type: Localhost\n        localhostProfile: profiles/demo-api.json"),
        },
        "KSP-POD-011": {
            "positive": pod_custom("pod-011-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      readOnlyRootFilesystem: true"),
            "negative": pod_custom("pod-011-negative", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      readOnlyRootFilesystem: false"),
            "boundary": pod_custom("pod-011-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      readOnlyRootFilesystem: true\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      readOnlyRootFilesystem: true"),
        },
        "KSP-POD-013": {
            "positive": pod_custom("pod-013-positive", "securityContext:\n  runAsUser: 1000\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0"),
            "negative": pod_custom("pod-013-negative", "securityContext:\n  runAsUser: 0\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0"),
            "boundary": pod("pod-013-boundary-unset"),
        },
        "KSP-POD-014": {
            "positive": pod_custom("pod-014-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    ports:\n      - containerPort: 8080"),
            "negative": pod_custom("pod-014-negative", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    ports:\n      - containerPort: 8080\n        hostPort: 8080"),
            "boundary": pod("pod-014-boundary-no-ports"),
        },
        "KSP-RES-001": {
            "positive": pod_custom("res-001-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        cpu: 100m"),
            "negative": pod("res-001-negative"),
            "boundary": pod_custom("res-001-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        cpu: 100m\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        cpu: 50m"),
        },
        "KSP-RES-002": {
            "positive": pod_custom("res-002-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        memory: 128Mi"),
            "negative": pod("res-002-negative"),
            "boundary": pod_custom("res-002-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        memory: 128Mi\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      requests:\n        memory: 64Mi"),
        },
        "KSP-RES-003": {
            "positive": pod_custom("res-003-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        cpu: 500m"),
            "negative": pod("res-003-negative"),
            "boundary": pod_custom("res-003-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        cpu: 500m\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        cpu: 250m"),
        },
        "KSP-RES-004": {
            "positive": pod_custom("res-004-positive", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        memory: 512Mi"),
            "negative": pod("res-004-negative"),
            "boundary": pod_custom("res-004-boundary-init", "containers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        memory: 512Mi\ninitContainers:\n  - name: init\n    image: harbor.example.com/demo-api:1.0.0\n    resources:\n      limits:\n        memory: 256Mi"),
        },
    }


def build_catalog():
    cases = positive_negative_boundary()
    cases.update({
        "KSP-META-001": {
            "positive": workload("Deployment", "meta-001-positive", {"app.kubernetes.io/name": "demo-api"}),
            "negative": workload("Deployment", "meta-001-negative"),
            "boundary": workload("CronJob", "meta-001-boundary", {"app.kubernetes.io/name": "demo-api"}),
            "kind": "Deployment",
            "boundary_kind": "CronJob",
        },
        "KSP-META-002": {
            "positive": workload("Deployment", "meta-002-positive", {"policies.ksp.io/owner": "platform-team"}),
            "negative": workload("Deployment", "meta-002-negative"),
            "boundary": workload("StatefulSet", "meta-002-boundary", {"policies.ksp.io/owner": "security-team"}),
            "kind": "Deployment",
            "boundary_kind": "StatefulSet",
        },
        "KSP-META-003": {
            "positive": workload("Deployment", "meta-003-positive", {"policies.ksp.io/environment": "dev"}),
            "negative": workload("Deployment", "meta-003-negative", {"policies.ksp.io/environment": "prod"}),
            "boundary": workload("Job", "meta-003-boundary", {"policies.ksp.io/environment": "production"}),
            "kind": "Deployment",
            "boundary_kind": "Job",
        },
    })
    cases["KSP-POD-012"] = {
        "type": "mutate",
        "positive": multi(
            namespace("security-test", {"policies.ksp.io/mutate-default-security-context": "enabled"}),
            pod("pod-012-positive", namespace="security-test"),
        ),
        "negative": multi(namespace("policy-test"), pod("pod-012-negative")),
        "boundary": multi(
            namespace("security-test", {"policies.ksp.io/mutate-default-security-context": "enabled"}),
            pod_custom("pod-012-boundary-existing", "securityContext:\n  runAsNonRoot: true\n  seccompProfile:\n    type: RuntimeDefault\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false\n      readOnlyRootFilesystem: true\n      capabilities:\n        drop: [ALL]", namespace="security-test"),
        ),
        "patched": pod_custom("pod-012-positive", "securityContext:\n  runAsNonRoot: true\n  seccompProfile:\n    type: RuntimeDefault\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false\n      readOnlyRootFilesystem: true\n      capabilities:\n        drop: [ALL]", namespace="security-test"),
        "boundary_patched": pod_custom("pod-012-boundary-existing", "securityContext:\n  runAsNonRoot: true\n  seccompProfile:\n    type: RuntimeDefault\ncontainers:\n  - name: demo-api\n    image: harbor.example.com/demo-api:1.0.0\n    securityContext:\n      allowPrivilegeEscalation: false\n      readOnlyRootFilesystem: true\n      capabilities:\n        drop: [ALL]", namespace="security-test"),
        "kind": "Pod",
    }
    cases["KSP-META-004"] = {
        "type": "mutate",
        "positive": workload("Deployment", "meta-004-positive", {"app.kubernetes.io/name": "demo-api"}),
        "negative": pod("meta-004-negative-pod"),
        "boundary": workload("Deployment", "meta-004-boundary", {"app.kubernetes.io/managed-by": "platform", "app.kubernetes.io/name": "demo-api"}),
        "patched": workload("Deployment", "meta-004-positive", {"app.kubernetes.io/name": "demo-api", "app.kubernetes.io/managed-by": "kyverno", "policies.ksp.io/governed": '"true"'}),
        "boundary_patched": workload("Deployment", "meta-004-boundary", {"app.kubernetes.io/managed-by": "platform", "app.kubernetes.io/name": "demo-api", "policies.ksp.io/governed": '"true"'}),
        "kind": "Deployment",
    }
    cases["KSP-RES-005"] = generate_case(
        "res-005", "generate-resource-quota", "namespace-resource-quota", "ResourceQuota",
        "v1",
        "spec:\n  hard:\n    requests.cpu: \"4\"\n    requests.memory: 8Gi\n    limits.cpu: \"8\"\n    limits.memory: 16Gi\n    pods: \"50\"",
        "policies.ksp.io/generated-by: ksp-res-005",
    )
    cases["KSP-RES-006"] = generate_case(
        "res-006", "generate-limit-range", "container-resource-defaults", "LimitRange",
        "v1",
        "spec:\n  limits:\n    - type: Container\n      defaultRequest: {cpu: 100m, memory: 128Mi}\n      default: {cpu: 500m, memory: 512Mi}\n      min: {cpu: 25m, memory: 32Mi}\n      max: {cpu: \"2\", memory: 2Gi}",
        "policies.ksp.io/generated-by: ksp-res-006",
    )
    cases["KSP-NET-001"] = generate_case(
        "net-001", "generate-default-deny-network-policy", "default-deny-ingress-egress", "NetworkPolicy",
        "networking.k8s.io/v1",
        "spec:\n  podSelector: {}\n  policyTypes: [Ingress, Egress]\n  ingress: []\n  egress: []",
        "policies.ksp.io/generated-by: ksp-net-001",
        label_key="policies.ksp.io/generate-network-baseline",
    )
    return cases


def generate_case(prefix, policy, generated_name, kind, api, body, generated_by, label_key="policies.ksp.io/generate-resource-governance"):
    positive_ns = f"{prefix}-positive"
    boundary_ns = f"{prefix}-boundary"
    return {
        "type": "generate",
        "positive": namespace(positive_ns, {label_key: "enabled"}),
        "negative": namespace(f"{prefix}-negative"),
        "boundary": namespace(boundary_ns, {label_key: "enabled", "policies.ksp.io/environment": "dev"}),
        "generated": generated_resource(api, kind, generated_name, positive_ns, generated_by, body),
        "boundary_generated": generated_resource(api, kind, generated_name, boundary_ns, generated_by, body),
        "kind": "Namespace",
    }


def generated_resource(api, kind, name, ns, generated_by, body):
    return docs(f"""
apiVersion: {api}
kind: {kind}
metadata:
  name: {name}
  namespace: {ns}
  labels:
    app.kubernetes.io/managed-by: kyverno
    {generated_by}
{body}
""")


META = {
    "KSP-IMG-001": ("image-security", "KSP-IMG-001-disallow-latest-tag.yaml", "disallow-latest-tag", "disallow-latest-tag", "Pod", "controlled"),
    "KSP-IMG-002": ("image-security", "KSP-IMG-002-approved-registry-allowlist.yaml", "approved-registry-allowlist", "approved-registry-allowlist", "Pod", "controlled"),
    "KSP-IMG-003": ("image-security", "KSP-IMG-003-require-image-digest.yaml", "require-image-digest", "require-image-digest", "Pod", "controlled"),
    "KSP-IMG-004": ("image-security", "KSP-IMG-004-verify-signed-images.yaml", "verify-signed-images", "verify-signed-images", "Pod", "controlled"),
    "KSP-META-001": ("metadata", "KSP-META-001-require-app-label.yaml", "require-app-label", "require-app-label", "Deployment", "limited"),
    "KSP-META-002": ("metadata", "KSP-META-002-require-owner-label.yaml", "require-owner-label", "require-owner-label", "Deployment", "limited"),
    "KSP-META-003": ("metadata", "KSP-META-003-require-environment-label.yaml", "require-environment-label", "require-environment-label", "Deployment", "limited"),
    "KSP-META-004": ("metadata", "KSP-META-004-add-default-labels.yaml", "add-default-labels", "add-default-labels", "Deployment", "none"),
    "KSP-NET-001": ("network-security", "KSP-NET-001-generate-default-deny-network-policy.yaml", "generate-default-deny-network-policy", "generate-default-deny-network-policy", "Namespace", "controlled"),
    "KSP-POD-001": ("pod-security", "KSP-POD-001-require-run-as-non-root.yaml", "require-run-as-non-root", "require-run-as-non-root", "Pod", "controlled"),
    "KSP-POD-002": ("pod-security", "KSP-POD-002-disallow-privileged.yaml", "disallow-privileged", "disallow-privileged", "Pod", "controlled"),
    "KSP-POD-003": ("pod-security", "KSP-POD-003-disallow-privilege-escalation.yaml", "disallow-privilege-escalation", "disallow-privilege-escalation", "Pod", "controlled"),
    "KSP-POD-004": ("pod-security", "KSP-POD-004-disallow-host-network.yaml", "disallow-host-network", "disallow-host-network", "Pod", "controlled"),
    "KSP-POD-005": ("pod-security", "KSP-POD-005-disallow-host-pid.yaml", "disallow-host-pid", "disallow-host-pid", "Pod", "controlled"),
    "KSP-POD-006": ("pod-security", "KSP-POD-006-disallow-host-ipc.yaml", "disallow-host-ipc", "disallow-host-ipc", "Pod", "controlled"),
    "KSP-POD-007": ("pod-security", "KSP-POD-007-restrict-host-path.yaml", "restrict-host-path", "restrict-host-path", "Pod", "controlled"),
    "KSP-POD-008": ("pod-security", "KSP-POD-008-drop-all-capabilities.yaml", "drop-all-capabilities", "drop-all-capabilities", "Pod", "controlled"),
    "KSP-POD-009": ("pod-security", "KSP-POD-009-restrict-added-capabilities.yaml", "restrict-added-capabilities", "restrict-added-capabilities", "Pod", "controlled"),
    "KSP-POD-010": ("pod-security", "KSP-POD-010-require-seccomp.yaml", "require-seccomp", "require-seccomp", "Pod", "controlled"),
    "KSP-POD-011": ("pod-security", "KSP-POD-011-require-read-only-root-filesystem.yaml", "require-read-only-root-filesystem", "require-read-only-root-filesystem", "Pod", "controlled"),
    "KSP-POD-012": ("pod-security", "KSP-POD-012-add-default-security-context.yaml", "add-default-security-context", "add-default-security-context", "Pod", "controlled"),
    "KSP-POD-013": ("pod-security", "KSP-POD-013-disallow-run-as-user-zero.yaml", "disallow-run-as-user-zero", "disallow-run-as-user-zero", "Pod", "controlled"),
    "KSP-POD-014": ("pod-security", "KSP-POD-014-restrict-host-ports.yaml", "restrict-host-ports", "restrict-host-ports", "Pod", "controlled"),
    "KSP-RES-001": ("resource-governance", "KSP-RES-001-require-cpu-request.yaml", "require-cpu-request", "require-cpu-request", "Pod", "controlled"),
    "KSP-RES-002": ("resource-governance", "KSP-RES-002-require-memory-request.yaml", "require-memory-request", "require-memory-request", "Pod", "controlled"),
    "KSP-RES-003": ("resource-governance", "KSP-RES-003-require-cpu-limit.yaml", "require-cpu-limit", "require-cpu-limit", "Pod", "controlled"),
    "KSP-RES-004": ("resource-governance", "KSP-RES-004-require-memory-limit.yaml", "require-memory-limit", "require-memory-limit", "Pod", "controlled"),
    "KSP-RES-005": ("resource-governance", "KSP-RES-005-generate-resource-quota.yaml", "generate-resource-quota", "generate-resource-quota", "Namespace", "controlled"),
    "KSP-RES-006": ("resource-governance", "KSP-RES-006-generate-limit-range.yaml", "generate-limit-range", "generate-limit-range", "Namespace", "controlled"),
}


def resource_name(yaml_text):
    for line in yaml_text.splitlines():
        if line.startswith("  name: "):
            return line.split(": ", 1)[1].strip()
    raise ValueError("metadata.name not found")


def write_case(policy_id, case):
    group, policy_file, policy, rule, kind, exception_mode = META[policy_id]
    test_dir = POLICIES / group / policy_id / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    for filename in ["positive.yaml", "negative.yaml", "boundary.yaml", "exception.yaml", "exception-resource.yaml", "positive-patched.yaml", "boundary-patched.yaml", "positive-generated.yaml", "boundary-generated.yaml"]:
        path = test_dir / filename
        if path.exists():
            path.unlink()
    (test_dir / "positive.yaml").write_text(case["positive"], encoding="utf-8")
    (test_dir / "negative.yaml").write_text(case["negative"], encoding="utf-8")
    (test_dir / "boundary.yaml").write_text(case["boundary"], encoding="utf-8")

    files = ["positive.yaml", "negative.yaml", "boundary.yaml"]
    results = []
    ctype = case.get("type", "validate")
    positive_name = resource_name(case["positive"].split("---")[-1] if ctype == "mutate" else case["positive"])
    negative_names = case.get("negative_resources") or [resource_name(case["negative"].split("---")[-1])]
    boundary_name = resource_name(case["boundary"].split("---")[-1] if ctype == "mutate" else case["boundary"])
    boundary_kind = case.get("boundary_kind", kind)

    if ctype == "mutate":
        (test_dir / "positive-patched.yaml").write_text(case["patched"], encoding="utf-8")
        (test_dir / "boundary-patched.yaml").write_text(case["boundary_patched"], encoding="utf-8")
        results.extend([
            result(policy, rule, kind, [positive_name], "pass", patched="positive-patched.yaml"),
            result(policy, rule, kind, negative_names, "skip"),
            result(policy, rule, kind, [boundary_name], "pass", patched="boundary-patched.yaml"),
        ])
    elif ctype == "generate":
        (test_dir / "positive-generated.yaml").write_text(case["generated"], encoding="utf-8")
        (test_dir / "boundary-generated.yaml").write_text(case["boundary_generated"], encoding="utf-8")
        results.extend([
            result(policy, rule, kind, [positive_name], "pass", generated="positive-generated.yaml"),
            result(policy, rule, kind, negative_names, "skip"),
            result(policy, rule, kind, [boundary_name], "pass", generated="boundary-generated.yaml"),
        ])
    else:
        results.extend([
            result(policy, rule, kind, [positive_name], case.get("positive_result", "pass")),
            result(policy, rule, kind, negative_names, "fail"),
            result(policy, rule, boundary_kind, [boundary_name], case.get("boundary_result", "pass")),
        ])

    if exception_mode != "none":
        ex_name = f"{policy_id.lower()}-exception"
        if policy_id == "KSP-IMG-004":
            ex_res = pod(ex_name, image=f"harbor.example.com/demo-api@sha256:{DIGEST}")
        elif ctype == "generate":
            ex_res = namespace(ex_name, {"policies.ksp.io/generate-resource-governance": "enabled", "policies.ksp.io/generate-network-baseline": "enabled"})
        elif ctype == "mutate":
            ex_res = multi(
                namespace("security-test", {"policies.ksp.io/mutate-default-security-context": "enabled"}),
                pod(ex_name, namespace="security-test"),
            )
        elif kind == "Deployment":
            ex_res = workload("Deployment", ex_name)
        else:
            ex_res = case["negative"].split("---")[0].replace(negative_names[0], ex_name)
        (test_dir / "exception-resource.yaml").write_text(ex_res, encoding="utf-8")
        (test_dir / "exception.yaml").write_text(
            exception(policy, rule, kind, ex_name, "security-test" if ctype == "mutate" else "policy-test"),
            encoding="utf-8",
        )
        files.append("exception-resource.yaml")
        results.append(result(policy, rule, kind, [ex_name], "skip"))

    kyverno = docs(f"""
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: {policy_id.lower()}-{policy}
policies:
  - ../{policy_file}
resources:
{chr(10).join(f"  - {f}" for f in files)}
{("exceptions:" + chr(10) + "  - exception.yaml" + chr(10)) if exception_mode != "none" else ""}results:
{''.join(results).rstrip()}
""")
    (test_dir / "kyverno-test.yaml").write_text(kyverno, encoding="utf-8")


def result(policy, rule, kind, resources, expected, patched=None, generated=None):
    extras = ""
    if patched:
        extras += f"    patchedResource: {patched}\n"
    if generated:
        extras += f"    generatedResource: {generated}\n"
    resources_block = "\n".join(f"      - {r}" for r in resources)
    return f"""  - policy: {policy}
    rule: {rule}
    kind: {kind}
    resources:
{resources_block}
{extras}    result: {expected}
"""


def main():
    catalog = build_catalog()
    missing = set(META) - set(catalog)
    if missing:
        raise SystemExit(f"Missing test data for: {sorted(missing)}")
    for policy_id in sorted(META):
        write_case(policy_id, catalog[policy_id])
    print(f"Generated tests for {len(META)} policies.")


if __name__ == "__main__":
    main()
