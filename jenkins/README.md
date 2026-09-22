# Jenkins CI and secure delivery

Two independent jobs separate framework correctness from application releases.
`Jenkinsfile.ci` migrates GitLab's gates; `Jenkinsfile.delivery` builds and deploys
one small dependency-free Python HTTP service. Both call scripts rather than
embedding the implementation in Groovy. Neither installs Jenkins or modifies
Kyverno policies. All commands below run from the repository root.

**Delivery is currently blocked by an existing policy conflict.** Production
Standard/Restricted IMG-002 accepts `harbor.example.com/`, `registry.k8s.io/` and
`reg.kyverno.io/`. The required target is `harbor-public:30003/ksp-test`, which is
also IMG-004's signature scope. The demo stays Restricted and expects every
applicable validation to pass; its preflight fails on the allowlist. No automatic
exception, profile downgrade, policy deletion, or policy rewrite is provided.
The policy owner must resolve the registry naming/trust contract in a separate,
reviewed change before this exact delivery flow can succeed. Simply changing the
image hostname would move it outside the current signature policy scope.

## Architecture and agents

```text
GitHub -> Jenkins controller (jenkins namespace, zero executors)
           |-> ephemeral ksp-tools Kubernetes agents
           |     |-> framework validation / Kyverno CLI
           |     `-> delivery -> mTLS BuildKit -> local archive -> Trivy
           |                    -> Harbor -> Cosign -> Kubernetes API
           |                    -> Kyverno admission -> kubelet/containerd pull
           |                    -> rollout -> reports -> HTTP health
           `-> isolated ksp-kind host agent -> temporary Kind cluster

Cluster: jenkins / kyverno / harbor / monitoring / ksp-demo
```

The controller uses the official [Jenkins chart](https://github.com/jenkinsci/helm-charts)
and only schedules work. Helm's Kubernetes cloud provisions `ksp-tools` Pods with
an `emptyDir` workspace, no service-account token, non-root UID 1000, a read-only
root filesystem, dropped capabilities and RuntimeDefault seccomp. Configure the
agent image before running jobs: the chart's upstream remoting image has no tools.
Controller RBAC is the chart's namespace-scoped agent management, not cluster-admin.
Delivery Kubernetes access is separately bound only during deployment/evidence.

`ksp-kind` must be a **dedicated disposable Linux host/VM**, with Jenkins remoting,
Python/PyYAML, the pinned tools and a working **local** Docker or supported rootless
container runtime. Give it one executor. Do not mount the host Docker socket into
the controller or agent Pods. No privileged DinD is used. The runtime needed to
run Kubernetes nodes is kept outside the policy-enforced application cluster.
A unique Kind name and private temporary kubeconfig isolate each run. Shell traps
export logs/delete the cluster; Jenkins makes a second deletion attempt. If a host
is forcibly lost, the host lifecycle/reaper must remove orphaned `ksp-*` clusters;
no process can guarantee cleanup after machine loss.

BuildKit is a separate operator-provisioned worker accessed with **mTLS**. A
rootless worker on an isolated host is the default recommendation. Kubernetes
BuildKit workers are also possible only where their security requirements pass
existing policy. The upstream [rootless BuildKit constraints](https://github.com/moby/buildkit/blob/master/docs/rootless.md)
can require unconfined seccomp/AppArmor or process-sandbox changes; this repository
does not apply those changes to bypass enforcement. Provide an isolated worker
per trust boundary and an endpoint whose certificate matches its DNS hostname.
Use the version in `versions.yaml`; no BuildKit service is installed by these jobs.

## Toolchain and versions

`versions.yaml` retains all existing platform/GitLab pins. Jenkins adds the chart,
remoting base image, Trivy, BuildKit, Crane and a fixed kubectl version. The
previously unspecified Cosign version is now pinned. Existing Kyverno CLI/chart,
Kind, Helm, Python base image and PyYAML versions are reused. These pins are
reproducible baselines, not a claim that they are the newest or free of CVEs.
The local install script targets **linux/amd64**; delivery images have that same
platform. Scan and review tool/agent updates independently of policy changes.

Build the agent on an operator build host (not on the controller):

```bash
source jenkins/scripts/common.sh
# Choose a registry/image name compatible with the cluster's existing policies.
docker build -f jenkins/Dockerfile.agent \
  --build-arg "AGENT_IMAGE=$(version jenkins.agent_image)" \
  --build-arg "PYTHON_IMAGE=$(version ci.python.image)" \
  --build-arg "PYYAML_VERSION=$(version ci.pyyaml.version)" \
  -t YOUR_APPROVED_REGISTRY/ci/ksp-agent:BUILD_VERSION .
```

Push, scan, resolve its digest and configure `agent.image` in an ignored
`helm/jenkins/site-values.yaml`. For this chart, a tag value of
`BUILD_VERSION@sha256:<real-digest>` produces a digest-pinned image. Mirror the
controller and other chart images into approved locations too. Evaluate the
result; a repository prefix does not by itself establish signature coverage.
No image digest is fabricated or prefilled. Install the Harbor CA into the agent
system trust store and the worker's trust store through your image/configuration
management. Keep ordinary public roots as well. Never use insecure registry flags.

For a disposable host, the same `jenkins/scripts/install-tools.sh` installs tools
into `TOOLS_BIN` (default `/usr/local/bin`); Python and pinned PyYAML are prerequisites.
Downloads use HTTPS release URLs. Additional independent checksum/signature
verification of tool downloads and a locked agent image supply chain are production
hardening tasks; the agent image build has not been executed here.

## Plugins

Required: **Pipeline** (`workflow-aggregator`), **Git** (`git`), **Kubernetes**
(`kubernetes`), **Credentials Binding** (`credentials-binding`), **JUnit** (`junit`),
**Configuration as Code** (`configuration-as-code`), and **GitHub Branch Source**
(`github-branch-source`) for multibranch/webhook integration. Credentials and
Pipeline dependencies install with these plugins. The chart pins its four core
plugins; install/review the remaining plugins compatible with the chart's Jenkins
core using Manage Jenkins > Plugins, then record the tested plugin inventory in
site configuration. `installLatestPlugins: false` avoids floating dependencies;
`initializeOnce: true` requires explicit operator action for upgrades. Full plugin
resolution and Groovy execution still require a Jenkins instance.

## Jenkins credentials

Scope credentials to the trusted jobs/folder; do not run credential-bearing stages
from untrusted fork pull requests. Framework IMG-004 also needs registry access.
Use a read-only Harbor robot for framework CI and a project-scoped writer for
delivery; folder-local credentials may share the same ID with different permissions.

| ID | Jenkins type | Use |
|---|---|---|
| `github-credentials` | Username/password with token as password, or SSH private key for SSH SCM URL | GitHub checkout, configured in each job's SCM |
| `harbor-credentials` | Username with password | HTTPS `/v2/`, CLI registry tests, image/signature push/pull |
| `cosign-private-key` | Secret file | Encrypted Cosign private key corresponding to committed `image-security/cosign/cosign.pub` |
| `cosign-password` | Secret text | Cosign key password (`COSIGN_PASSWORD`) |
| `kubeconfig` | Secret file | Dedicated deployment identity with trusted server CA |
| `buildkit-ca` | Secret file | BuildKit server CA certificate |
| `buildkit-client-cert` | Secret file | BuildKit mTLS client certificate |
| `buildkit-client-key` | Secret file | BuildKit mTLS private key |

`jenkins-admin` is a **Kubernetes Secret**, not a Jenkins credential. Provision it
outside Git in namespace `jenkins`, with keys `jenkins-admin-user` and
`jenkins-admin-password`, before Helm installation. No generation command includes
a literal secret. The existing ignored local `.key` files are not pipeline inputs.
Harbor auth files live in a temporary directory outside the archive tree and are
removed on exit. Jenkins secret bindings and tracing-disabled scripts prevent
intentional logging; never archive the whole workspace or `$WORKSPACE@tmp`.

## Pipeline 1: framework CI

```text
Checkout -> Validate -> CLI Unit Test -> Rendered Policy Test -> Kind Integration
         -> Collect Results -> Archive Artifacts (finalization, including failure)
```

Validation preserves GitLab's policy config/version checks, profile counts
13/27/29, source/test references and YAML parsing, coverage structure, all-environment
rendering, Git drift detection, and Harbor HTTPS authentication. `.gitlab-ci.yml`
is still read by the existing version validator and must remain.

CLI Unit Test is the **only full regression gate**. It discovers exactly 29
canonical manifests, runs text and JUnit invocations per suite with `--registry`,
continues across individual failures, and fails after the aggregate summary.
The two invocations preserve GitLab's evidence behavior, not two regression stages.
The existing JUnit extraction workaround is retained. A suite-count mismatch fails
before running any suite. Missing registry connectivity/authentication never turns
signature tests into expected failures or skips.

The rendered-production META-003 tests remain a separate integration prerequisite.
Kind installs the existing chart version with one replica per controller, matching
GitLab (the multi-node production values are intentionally not used). It renders
and applies all production policies, waits for readiness, preserves the original
isolated POD-010 positive/negative check, then applies **common + Baseline** for an
additional complete Baseline admission check. The compliant bootstrap image is
outside Harbor signature scope; this is **not** proof of Harbor signature enforcement.
A negative request must explicitly identify `require-seccomp` and denial, and the
Pod must be absent. Policy installation, readiness and positive admission errors fail.
Jenkins runs Kind on every successful CI run, a coverage superset of GitLab's
path-filtered execution. Kubernetes readiness is checked; Pod scheduling is not
needed to establish these admission decisions.

Artifacts preserve `artifacts/validate`, `check-policy`, `cli-unit`,
`rendered-policy-test`, `integration-kind`, `e2e` and `report`. On fresh Jenkins
checkouts, historical tracked evidence is removed **only from the job workspace**,
so old JUnit files cannot masquerade as current results. Git history is untouched.
JUnit is published, all evidence is archived even after failed gates, retention is
30 days (GitLab's CLI retention was 14 days). The existing E2E collector additionally
records controller/report/event evidence; optional Prometheus snapshots can be
unavailable without invalidating admission tests.

## Pipeline 2: delivery

```text
Checkout -> Source Check -> Security Scan -> Build Image -> Image Vulnerability Scan
 -> Push to Harbor -> Resolve Digest -> Cosign Sign -> Cosign Verify
 -> Render Kubernetes Manifest -> Pre-deployment Kyverno Test
 -> Kubernetes Deployment / Kyverno Admission -> Rollout Verification
 -> PolicyReport Collection -> Application Health Check -> Archive Evidence
```

Trivy is selected because one open-source CLI scans source secrets/configuration,
dependency inventories when present, and a local container archive. This app uses
only Python's standard library, so there is no third-party dependency lockfile.
Both scan gates fail on **HIGH or CRITICAL**, including unfixed findings; scanner
errors also fail. No ignore file, skip-scan switch or severity downgrade is supplied.
The older preserved Python base may require a separately reviewed version update
if the vulnerability gate rejects it. Source checks parse Python and Kubernetes YAML.

BuildKit produces one local Docker-format image archive named
`harbor-public:30003/ksp-test/demo-app:${BUILD_NUMBER}`. Trivy scans that archive;
Crane pushes the same bytes. The remote manifest digest must match the archive's
manifest digest, protecting against tag replacement. After that comparison, every
sign/verify/render/deploy operation uses `image@sha256`. The archive checksum,
build metadata, remote manifest and immutable reference are evidence.

Cosign compares the credential's public key to the committed key before signing,
then signs and independently verifies the digest. Normal transparency logging and
verification are enabled; Rekor/Sigstore connectivity is required. The existing
Kyverno IMG-004 `insecureIgnoreTlog: true` is left unchanged: it concerns log
verification, **not TLS verification**. Harbor must allow the signature objects
written by the pinned Cosign release. Do not garbage-collect those signatures while
images remain in use.

Manifest rendering preserves source YAML and emits a Deployment, Namespace,
Service, NetworkPolicy and representative Pod under the build artifacts. The Pod
is explicitly tested because many repository CEL rules match Pods directly. The
Kyverno test loads all 29 rendered production policies, supplies Restricted namespace
labels and expects passes for every applicable validating/image policy; it does
not infer success from a zero-match run. Existing opt-in generation/defaulting is
not enabled for this application. Every relevant validation is explicitly configured
in the workload, including labels, non-root execution, seccomp, capabilities,
read-only filesystem and resources.

Deployment checks that live policies match the rendered production specs and are
Ready, records webhooks, confirms the namespace is already Production/Restricted,
runs **server-side Pod dry-run**, then `kubectl apply`. The actual ReplicaSet Pods
still go through Kyverno admission. The pipeline waits for rollout and verifies
replicas, Pod readiness/image references, ready EndpointSlices, then HTTP `/healthz`
through the Service DNS path from the in-cluster agent. No Jenkins `docker pull`
is involved: kubelet/containerd authenticates to Harbor and pulls the image.

PolicyReports and ClusterPolicyReports are archived with workload UIDs and timestamps
in their native objects. Summary correlation uses Pod/ReplicaSet/Deployment UIDs;
relevant fail/error results fail the report stage. Empty/asynchronous reports, skips
or the mere existence of a report do **not** prove all policies passed. IMG-004
background evaluation is disabled by the existing policy, so signature evidence
comes from CLI, Cosign and admission as well. Finalization collects diagnostic
reports/events even after a deployment failure. Report/API permission failures are
recorded and fail the collection stage.

Evidence: `artifacts/delivery/<BUILD_ID>/{source-check,scan,image,harbor,cosign,kyverno,deployment,policy-report,health}`.
Jenkins archives it for 30 days; the potentially large `image.tar` stays in the
workspace only, with its checksum archived. Credentials/kubeconfigs are excluded.
Delivery does not automatically uninstall or roll back a deployed application.

## Harbor, Kubernetes and monitoring prerequisites

- Create Harbor project `ksp-test`, robot permissions, DNS resolution for
  `harbor-public`, and a valid TLS certificate with that SAN. Existing Harbor
  `externalURL` points to an IP; reconcile token-service URL/DNS/certificates.
  Trust its CA on agents, BuildKit, Kyverno and all containerd nodes. The existing
  `helm/harbor/values-harbor-ca.yaml` describes Kyverno's CA mount; it must contain
  the full required trust bundle. Harbor's bundled Trivy is currently disabled;
  Jenkins scanning does not depend on it.
- A cluster administrator installs the existing production Kyverno bundle. The
  deployment credential must not create/update/delete policies or exceptions.
  Verify Kyverno configuration/resource filters and webhook selectors cover
  `ksp-demo`, failure behavior is closed, and no exception bypasses its workloads.
- Before running delivery, an administrator applies `demo-app/k8s/namespace.yaml`
  and provisions `harbor-registry-credentials` in `ksp-demo` for containerd pulls,
  and in Kyverno's namespace for IMG-004's registry verification. These are
  Kubernetes image-pull Secrets created through the site's secret-management
  process, not committed YAML and not copied from Jenkins into artifacts.
- Grant the kubeconfig identity get/patch/update on the existing `ksp-demo`
  namespace; get/list/watch/create/patch/update on its Deployments, Services and
  NetworkPolicies; get/list/watch Pods, ReplicaSets, events, EndpointSlices and
  PolicyReports; create Pods for server dry-run; read-only list/get for the four
  Kyverno policy types, validating webhooks and ClusterPolicyReports. A pre-existing
  namespace avoids granting broad namespace creation. No Secret-read permission
  is needed. Admission must handle dry-run requests normally.
- Agent Pods need outbound API, Harbor, BuildKit, GitHub/release, Trivy database,
  Sigstore/Rekor and app Service connectivity. NetworkPolicy permits app ingress
  from labeled Jenkins agents only and denies app egress; it assumes a CNI that
  enforces NetworkPolicy. If the Jenkins namespace also has default-deny egress,
  the platform operator must supply narrow egress rules.
- Existing Prometheus/Grafana configuration is preserved. No monitoring files are
  moved or changed. Review admission latency, rejection and controller metrics
  alongside the archived evidence; successful HTTP alone is not policy evidence.

## Jobs, GitHub and migration

1. Complete [Helm preflight/install](../helm/jenkins/README.md), provision the
   toolbox image and Kind host, install plugins and folder-scoped credentials.
2. Create a Pipeline-from-SCM job `ksp-framework-ci`: Git SCM, GitHub repo URL,
   `github-credentials`, trusted branch, script path **`Jenkinsfile.ci`**. For
   multibranch, use GitHub Branch Source and configure that script path.
3. Create an independent trusted-branch Pipeline-from-SCM job `ksp-delivery`, same
   repository, script path **`Jenkinsfile.delivery`**. Set `BUILDKIT_HOST` to the
   real mTLS endpoint. Keep one deployment job per `ksp-demo` target; concurrent
   builds are disabled. Do not expose this job to untrusted PR Jenkinsfiles.
4. Set the externally reachable Jenkins HTTPS URL. Configure GitHub's webhook
   for `<JENKINS_URL>/github-webhook/`, JSON payload, shared webhook secret managed
   in Jenkins/GitHub, push/PR events as appropriate. Enable the job's matching
   GitHub trigger (or multibranch indexing). Validate a delivered event and record
   the commit/build association. Repository code does not configure webhooks.
5. Run **Pipeline 1** with Build Now. Require 29 suite entries, 29 valid JUnit
   reports, aggregate pass, rendered tests, Kind positive/negative evidence and
   cleanup success. Compare the same commit with GitLab, including Harbor fixtures.
   In a disposable test branch, deliberately break one expected policy input and
   verify later suites still run, Jenkins fails, and reports remain available.
   Interrupt Kind once and verify cluster deletion. Do not change canonical tests
   to accommodate unavailable Harbor or an unexpected admission decision.
6. Run **Pipeline 2** only after its prerequisites and the registry contract have
   been resolved by the policy owner. Check each archived stage, digest identity,
   signature, exact deployed image and HTTP response. In a disposable environment,
   wrong signing key, unsigned image, invalid workload and failed health endpoint
   must stop promotion. Registry/preflight errors must never fall through to apply.
7. Keep GitLab and Jenkins in parallel until equivalence is demonstrated across
   success, policy failure, infrastructure failure and cancellation cases. Record
   commit IDs, versions, suite counts and artifacts in the migration review. Then
   switch required GitHub status checks and triggers. **`.gitlab-ci.yml` must only
   be removed after Jenkins Pipeline 1 demonstrates equivalent CI coverage**;
   update the existing validator's GitLab pin dependency in that later change.

## Troubleshooting and current validation limits

| Symptom | Action |
|---|---|
| Agent waits forever | Check Kubernetes cloud label `ksp-tools`, image/tool contents, Pod events and policy denials; never run builds on controller as a workaround |
| Helm preflight denies | Read `artifacts/jenkins-helm/kyverno.txt`; fix rendered resources/image provenance, not policies |
| Harbor TLS/auth errors | Verify DNS, token-service URL, SANs, full CA bundle and project robot permissions; do not disable TLS |
| IMG-004 CLI failure | Verify fixture digests/signatures exist and trusted public key matches; retain expected test decisions |
| Delivery allowlist denial | Known IMG-002/IMG-004 hostname conflict; separate policy-owner decision required |
| Kind unavailable | Provision `ksp-kind` host/runtime and pinned tools; no DinD fallback |
| Live-policy drift | Reconcile the cluster through framework administration; the delivery job cannot rewrite policies |
| Apply succeeds but rollout fails | Inspect ReplicaSet/Pod events for admission, ImagePullBackOff, quota or scheduling failures |
| No report results | Reporting is asynchronous; inspect UIDs, background settings and controller health; do not call this compliance |
| Service health fails | Check EndpointSlices, probes, Service selector and Jenkins-to-app NetworkPolicy/DNS |

Local checks: `python3 -m unittest discover -s jenkins/tests -v`,
`bash jenkins/scripts/validate.sh`, `bash jenkins/scripts/check-policy.sh`,
`bash jenkins/scripts/rendered-policy-test.sh`. The CLI runner writes its normal
artifact paths; use a disposable checkout when running it because historical
reports are tracked in this repository. See [verification record](verification.md)
for actual executed checks. No Jenkins job, container build, Kind run, signing,
cluster deployment or successful end-to-end delivery is claimed without runtime
evidence. No service was installed as part of implementing this migration.
