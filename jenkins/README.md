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
| `jenkins-artifact-reader` | Username with password (Jenkins API token as password) | Read successful Policy CI build metadata and archived artifacts |

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

## Pipeline 2: Delivery PoC on the existing kubeadm cluster

First manual run parameters (the build number is selectable, not a fixed source):

```text
POLICY_CI_JOB=automated-tested
POLICY_CI_BUILD=21
POLICY_ENVIRONMENT=development
```

```text
Checkout -> Source Check -> Security Scan -> Build Image -> Image Vulnerability Scan
 -> Push to Harbor -> Resolve Digest -> Cosign Sign -> Cosign Verify
 -> Obtain Approved Policy Artifact -> Verify Approved Policy Artifact
 -> Deploy Approved Policies -> Verify Deployed Policies
 -> Render Kubernetes Manifest (demo app only)
 -> Kubernetes Deployment / Kyverno Admission -> Rollout Verification
 -> PolicyReport Collection -> Application Health Check -> Archive Evidence
```

**Artifact source.** There is no evidence of Copy Artifact in the repository's
plugin configuration. Delivery uses the Jenkins core JSON/archived-artifact API
and Python standard-library HTTP Basic authentication, with the existing
Credentials Binding plugin. Provision `jenkins-artifact-reader` as a username/API
-token credential with Overall/Read and Job/Read access to the source job (plus
artifact access if the installation restricts it). `JENKINS_URL` must be the
canonical URL reachable from the agent, with trusted TLS when HTTPS is configured.
HTTP remains supported for the current NodePort installation. Redirects are rejected
so credentials cannot be forwarded to another endpoint. Folder/job names work.
No controller filesystem, Policy CI workspace, Git policies, or latest-build
fallback is used. Only a completed `SUCCESS` build is accepted.

The archive may retain either Jenkins path
`artifacts/approved-policies-development/` or `approved-policies-development/`.
Exactly one matching prefix must exist. The downloaded package is verified before
any kubectl call: exact files/directories, no symlinks, environment annotations,
policy count, individual and aggregate SHA-256 inventory, `approval_mode=poc`,
coverage summary, and allowed deferral/non-applicability metadata. A receipt binds
all package files to source job/build and is rechecked before every cluster stage.
IMG-004's external-signature deferrals remain explicit in provenance; Cosign
verification of this demo image does not erase the Policy CI deferrals.

**Image assembly.** The existing agent already includes Python, tar support, and
`crane`. This demo has one standard-library Python file and needs no package
installation or Dockerfile RUN instruction. Delivery resolves the repository's
`ci.python.image` to its linux/amd64 digest, adds a deterministic non-root-owned
`/app/app.py` layer with `crane mutate --append --output`, and sets the non-root
user, command, workdir, environment, and port in a local Docker-format archive.
This is a dedicated demo assembler, not a general Dockerfile executor. The
Dockerfile remains an alternative operator build; Kubernetes HTTP readiness and
liveness probes supply health checks for the assembled image. Application code
changes are included automatically; adding dependencies or changing the runtime
contract requires updating the assembler. No Docker socket, root filesystem
writes, privileged agent, new agent image, or BuildKit service is needed.

Trivy scans the local archive before Crane pushes it. Existing HIGH/CRITICAL
scan gates, Harbor credentials, archive checksum, remote/local manifest digest
comparison, and Cosign key check/sign/verify are retained. No scan exceptions are
added. The Python base remains pinned in `versions.yaml`; a real Trivy finding
must be remediated, not bypassed. The local test host's Crane version is not proof
of the deployed agent version; flags were checked against the repository-pinned
Crane 0.20.3 implementation.

**Exact deployment path.** All policy apply arguments point under:

```text
$WORKSPACE/artifacts/delivery/$BUILD_ID/approved-policies-$POLICY_ENVIRONMENT/policies/
```

Apply order is common, baseline, standard, restricted. Every kubectl command
uses the `kubeconfig` secret-file credential explicitly; there is no in-cluster
service-account or default-config fallback. The selected kubeconfig context must
target the existing kubeadm cluster. Context name, API server and kube-system UID
are recorded without exporting the kubeconfig. Delivery changes the approved
cluster-wide policy set; use one trusted Delivery job per target cluster and avoid
concurrent external policy edits.

Verification compares approved identities and complete specs (allowing CRD defaults) against all four
`policies.kyverno.io` resource kinds. It rejects missing or unexpected KSP-labelled
policies, records other cluster policies, and reads CRD schemas for readiness.
It supports `status.conditionStatus.ready`, top-level ready, and Ready conditions;
no readiness field is required when the CRD exposes none. Six attempts, five
seconds apart, bound reconciliation waiting. Actual policy snapshots and readiness
comparisons are archived. No policy renderer is invoked by Delivery.

Only the four demo source manifests plus a representative Pod for server dry-run
are rendered. Namespace environment is `dev`, `staging`, or `production` while
the existing Restricted profile is preserved. Delivery applies the namespace,
performs server-side Pod admission dry-run, then applies the Deployment, Service,
and NetworkPolicy. The actual ReplicaSet Pods also undergo admission. Rollout,
replica counts, digest-pinned ready Pods, and ready Service EndpointSlices establish
application health; the Pod's HTTP readiness/liveness probes exercise `/healthz`.
No external ingress or agent-to-Service HTTP dependency is required.

Reports/events are correlated with workload UIDs. PolicyReports are sampled up to
six times at five-second intervals. Missing asynchronous results are explicitly
reported as unobserved, never PASS. Audit/Warn fail/error findings are retained as
findings; approved Deny-policy fail/error findings fail the report stage. API or
permission errors fail collection. The old production-only, all-pass offline
preflight was removed: source/rendered policy testing belongs to Policy CI, and
Delivery uses the actual kubeadm admission path. Applying a resource alone is not
claimed as proof that every webhook or policy evaluated it.

**Before the first manual run:**

- Keep `harbor-credentials`, `cosign-private-key`, `cosign-password`, and
  `kubeconfig`; add `jenkins-artifact-reader` as described above. Preserve the
  successful source build and its archived environment package.
- The kubeconfig identity now needs get/list/create/patch/update on all four
  cluster-scoped Kyverno policy kinds, and get on their CRDs. Previous read-only
  policy permissions are insufficient. It also needs namespace get/create/patch,
  app Deployment/Service/NetworkPolicy get/list/watch/create/patch/update,
  Pod create (dry-run), Pod/ReplicaSet/Event/EndpointSlice reads, report reads,
  and read access to validating/mutating webhook configurations. Do not grant
  Secret reads for this evidence collector.
- Provision `harbor-registry-credentials` in `ksp-demo` for kubelet pulls, and in
  Kyverno's namespace for IMG-004, through the existing secret-management process.
  Namespace creation by Delivery does not provision these secrets. Keep Harbor
  DNS/token-service URL/certificates and full CA trust correct for agents,
  Kyverno, and containerd nodes. Existing Kyverno and report CRDs/controllers must
  already be installed. No cluster is created by this pipeline.
- Allow agent access to Jenkins artifacts, the Python base registry, Trivy's DB,
  Harbor, Sigstore/Rekor, and the kubeadm API. Cosign's trusted key must match
  `image-security/cosign/cosign.pub` and the policy's key.
- **Known environment difference:** IMG-002's current approved allowlist names
  `harbor.example.com`, while the demo uses `harbor-public:30003`. Development and
  staging retain Audit/Warn; production Deny can reject this demo. Delivery must
  not repair this by weakening policies. A production run needs a separately
  approved framework/registry change and a new Policy CI artifact.

Evidence lives under `artifacts/delivery/<BUILD_ID>/`, including the exact
approved package, source provenance, policy apply/readiness snapshots, image
reference/signature results, app admission/rollout, reports and health. The image
archive is excluded from Jenkins archival; credentials and kubeconfigs are never
copied into evidence. No automatic rollback/uninstall is performed.

Offline checks: `python3 -B -m unittest discover -s jenkins/tests -v`.
These use synthetic Jenkins/registry/kubectl responses; they never contact a real
cluster. Actual build/scan/push/admission remains the user's manual Jenkins run.

## Jobs, GitHub and migration

1. Complete [Helm preflight/install](../helm/jenkins/README.md), provision the
   toolbox image and Kind host, install plugins and folder-scoped credentials.
2. Create a Pipeline-from-SCM job `ksp-framework-ci`: Git SCM, GitHub repo URL,
   `github-credentials`, trusted branch, script path **`Jenkinsfile.ci`**. For
   multibranch, use GitHub Branch Source and configure that script path.
3. Create an independent trusted-branch Pipeline-from-SCM job `ksp-delivery`, same
   repository, script path **`Jenkinsfile.delivery`**. Select the explicit successful
   Policy CI job/build/environment and provision `jenkins-artifact-reader`. Keep one deployment job per `ksp-demo` target; concurrent
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

Policy CI exposes `POLICY_ENVIRONMENT` with `development` (default), `staging`,
and `production`. One run renders the selected environment once, tests its
offline admission configuration and applicable cases, then packages
`artifacts/approved-policies-<environment>/`. The source CLI Unit gate is unchanged.
Rendered evidence distinguishes evaluation results from admission dispositions:
an Audit/Warn violation still expects CLI evaluation `fail`, but permits admission
with audit/warning rather than Deny. POD-012 disabled admission is structurally
verified and its canonical cases explicitly classified as non-applicable to
rendered admission. IMG-004 external signature cases remain deferred, while its
offline-safe cases execute. Neither classification means PASS.

`artifacts/rendered-policy-test/` contains the case plan, case coverage,
configuration assertions, runtime scenario ownership inventory, raw CLI results,
render receipt, and environment-bound success attestation. Packaging verifies
inputs, environment, evidence and exact policy bytes, and never renders again.
The 18 runtime scenarios remain E2E/Delivery-owned; they are not rendered skips.
See [design and implementation notes](../docs/environment-aware-policy-ci.md).

Local checks: `python3 -m unittest discover -s jenkins/tests -v`,
`python3 -B jenkins/scripts/test-approved-policies.py`,
`bash jenkins/scripts/validate.sh`, and
`POLICY_ENVIRONMENT=staging bash jenkins/scripts/rendered-policy-test.sh`, followed
by `POLICY_ENVIRONMENT=staging bash jenkins/scripts/package-approved-policies.sh`.
Do not run `check-policy.sh` separately before the rendered runner: the runner
already owns the single render. The CLI runner writes its normal
artifact paths; use a disposable checkout when running it because historical
reports are tracked in this repository. See [verification record](verification.md)
for actual executed checks. No Jenkins job, container build, Kind run, signing,
cluster deployment or successful end-to-end delivery is claimed without runtime
evidence. No service was installed as part of implementing this migration.
