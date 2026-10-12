# Jenkins CI and GitOps publication

Jenkins is CI and a GitOps publisher. Argo CD is CD/the reconciler. Kyverno is the
policy/admission engine. Harbor is the image registry. Git is desired state.
Monitoring owns policy/runtime observability.

```text
Policy source -> Jenkins Policy CI -> Validate -> CLI Unit Test
  -> Environment Render + Rendered Policy Test -> Approved Artifact (all 29)
  -> Policy Promotion (selected successful build + cumulative profile)
  -> GitOps policy desired state -> Argo CD Policy Application
  -> kube-apiserver -> Kyverno policies

Demo source -> Jenkins App CI -> Source Check -> Trivy -> Build Image
  -> Image Scan -> Push Harbor -> Resolve Digest -> Cosign Sign -> Cosign Verify
  -> GitOps application desired state -> Argo CD Demo Application
  -> kube-apiserver -> Kyverno admission -> workload

Monitoring -> PolicyReport / ClusterPolicyReport / Kyverno metrics
  -> dashboards / alerts
```

Both Argo Applications target the **same** in-cluster server,
`https://kubernetes.default.svc`. Jenkins pipelines do not deploy resources, access
Kubernetes, wait for rollout, or collect reports. The controller may still use its
existing namespace-scoped Kubernetes cloud permissions to provision build agents;
this does not grant deployment access to CI stages.

## Policy CI: Jenkinsfile.ci

The existing environment-aware pipeline is unchanged. Development is the default;
staging and production remain available for Policy CI. A run validates, executes
all canonical CLI suites, renders the selected environment, tests rendered policies,
and packages `artifacts/approved-policies-<environment>`. The approved development
artifact remains the **full 29-policy artifact**, including all four groups.
The render happens inside the rendered-policy test stage, never during promotion.
Collect Results and Archive Artifacts finalize the run, including failure evidence.

CLI tests, coverage accounting, render receipts, inventory hashes, environment
checks, PoC approval metadata and explicit IMG-004 external-signature deferrals
are preserved. Audit/Warn evaluation failures and explicit non-applicability are
not silently converted to passes. See
[environment-aware Policy CI](../docs/environment-aware-policy-ci.md).
Historical `runtime_e2e_owned_by_delivery` artifact fields remain unchanged for
compatibility; they are coverage gaps owned outside Jenkins CI, not evidence of
runtime testing by these pipelines. Runtime policy/report observability belongs
to monitoring; deployment and admission happen through Argo CD and Kyverno.

## Application CI: Jenkinsfile.delivery

Stages:

1. Checkout
2. Source Check
3. Security Scan
4. Build Image
5. Image Vulnerability Scan
6. Push to Harbor
7. Resolve Digest
8. Cosign Sign
9. Cosign Verify
10. Update Application GitOps Desired State
11. Archive Evidence (also on failure)

The existing dependency-free Python assembler uses `crane mutate` and a local
image archive. It resolves the pinned Python base to a platform-specific digest
and adds a deterministic non-root application layer. It needs no Docker daemon,
BuildKit, privileged Pod, or package installation. `demo-app/Dockerfile` and `src/`
remain build sources. Runtime dependencies would require a separately reviewed
assembler change.

Trivy retains HIGH/CRITICAL failure gates for source and local image scans.
The same secret/configuration gates also cover the migrated GitOps manifests. Harbor uses
the existing temporary authentication wrapper. The archive checksum is checked
before push; remote manifest digest must equal the scanned local archive digest.
The signing public key must match `image-security/cosign/cosign.pub`; Cosign signs
and verifies the immutable reference before Git publication. No scan exception,
TLS bypass, or signature bypass is introduced.

`gitops_app.py` reads `artifacts/delivery/$BUILD_ID/image/reference.txt` and requires
`harbor-public:30003/ksp-test/demo-app@sha256:<64 lowercase hex characters>`.
It identifies Deployment `ksp-demo/demo-app`, container `app`, and replaces only
the image scalar. Missing/ambiguous fields fail. Other manifest bytes are preserved;
no YAML serialization rewrites labels, probes, securityContext or formatting.

The four Kubernetes manifests now live only in `gitops/applications/demo-app/`.
`demo-app/k8s/` is removed. Namespace `ksp-demo` explicitly has
`ksp.io/environment: dev` (the framework's development value) and
`ksp.io/profile: baseline`. Security contexts, resource limits, probes, labels,
pull-secret reference, Service and NetworkPolicy are retained. The existing
NetworkPolicy's Jenkins-health ingress rule is preserved, though Jenkins no
longer performs health requests.

Evidence is under `artifacts/delivery/$BUILD_ID/`: source commit, scans, archive
checksum/build metadata, registry digest, Cosign results, image update, Git diff
and publication receipt. `image.tar` is excluded from archives. Git credentials
and the separate GitOps checkout are outside archived evidence.

## Policy promotion: Jenkinsfile.policy-promote

Use a separate trusted **manual** Pipeline-from-SCM job with these parameters:

| Parameter | Default / requirement |
|---|---|
| `POLICY_CI_JOB` | `automated-tested`; folder/job supported |
| `POLICY_CI_BUILD` | Empty; operator must select an explicit successful build number |
| `POLICY_ENVIRONMENT` | `development`; only development is exposed for this PoC |
| `POLICY_PROFILE` | `baseline`; also `standard` and `restricted` |

Stages: Checkout -> Obtain Approved Policy Artifact -> Verify Approved Policy
Artifact -> Select Profile and Update Policy GitOps Desired State -> Commit and
Push GitOps Change -> Archive Promotion Evidence (including failures).

`policy_artifact.py` uses the Jenkins archived-artifact API, authenticated by a
username/API-token binding. It requires a completed `SUCCESS` build, rejects
redirects, unsafe archive paths, ambiguous artifact prefixes and missing files.
It accepts the existing archive prefix with or without leading `artifacts/`.
No Copy Artifact plugin is required. `JENKINS_URL` must be the canonical reachable
URL; use trusted HTTPS where available. The verifier checks all files/directories,
symlinks, metadata, environment, policy identities/counts, per-file and aggregate
hashes, and coverage/deferral contracts. Its receipt binds the artifact to the
selected job/build and is rechecked by promotion.

| Profile | Selected directories | Current count |
|---|---|---:|
| baseline | common + baseline | 13 |
| standard | common + baseline + standard | 27 |
| restricted | common + baseline + standard + restricted | 29 |

Promotion always verifies the **complete** approved artifact first. It then reads
only the selected `approved-policies-development/policies/<group>/*.yaml` files
and copies their exact bytes. A temporary desired-state tree is verified before
replacing the previous tree; omitted groups are removed on downgrade. The sorted
Kustomization contains only selected policy paths. No policy source, renderer,
workspace-policy fallback, or YAML mutation is involved. The app namespace profile
is independent of which cumulative groups are installed: promotion does not
silently relabel workloads when more groups become available.

`provenance.json` is separate from policy YAML and excluded from Kustomization
resources. It records environment/profile, source job/build, artifact aggregate
SHA-256, source commit, UTC promotion timestamp, count and preserved deferrals.
Promotion evidence archives the downloaded approved artifact, retrieval and
verification receipts, promotion metadata, Git diff and publication receipt.

## Git publication and credentials

Both jobs use `gitops_publish.py` to clone the destination branch into a fresh
`.gitops-publish` checkout. The application publisher may stage only the Deployment;
the policy publisher may stage only `gitops/policies/development`. Unexpected
changes, pre-staged files and symlinks fail. Git commits use the CI bot identity
and `[skip ci]`. Pushes never force, rebase or silently resolve a conflict. If two
jobs race, a non-fast-forward push fails; rerun from a fresh checkout to compose
with the latest desired state. A no-change application update makes no commit.

Job environment settings (trusted job configuration, not user-supplied secrets):

| Setting | Default |
|---|---|
| `GITOPS_REPOSITORY` | `https://github.com/Hikaru2035/k8s_kyverno.git` |
| `GITOPS_BRANCH` | `cicd/jenkins` |
| `GITOPS_CHECKOUT` | `.gitops-publish` within the fresh Jenkins workspace |

The publisher accepts credential-free HTTPS URLs only. A temporary `GIT_ASKPASS`
script reads Jenkins-bound environment variables; it contains no credential
values, is removed on exit, and Git tracing is disabled. Credentials are never
placed in URLs, commit text, receipts, or logs. Existing credential helpers are
disabled for these operations. Failed Git operations emit a sanitized error.

| Credential ID | Jenkins type | Purpose |
|---|---|---|
| `github-credentials` | SCM-compatible credential | Existing source checkout configuration |
| `harbor-credentials` | Username/password | Existing Harbor registry authentication |
| `cosign-private-key` | Secret file | Encrypted matching signing key |
| `cosign-password` | Secret text | Cosign key password |
| `jenkins-artifact-reader` | Username/password (API token) | Read selected successful Policy CI archives |
| `gitops-git-credentials` | Username/password (Git token as password) | Dedicated least-privilege GitOps writer |

No `kubeconfig` credential is needed by these pipelines. Keep credentials scoped
to trusted jobs/folders; never execute credential-bearing stages for untrusted PRs.
Use a registry reader for Policy CI and a project writer for App CI where possible.
The Git writer needs read/write access to the destination branch; branch protection
must permit the intended bot publication workflow. An Argo CD repository credential,
if needed, is separately provisioned read-only; it is not a Jenkins credential.

Prevent loops using job/path separation: Policy CI watches framework/config/test
inputs, App CI watches demo build inputs and relevant CI/tool version changes,
and promotion is manually triggered. Exclude GitOps-only bot commits from both CI
triggers. `[skip ci]` is an additional marker, not a substitute for Jenkins trigger
configuration. Webhook/multibranch settings are operator configuration. Do not
trigger either CI job on every GitOps commit without filtering.

To move desired state into a separate repository, seed its `gitops/` tree, set
`GITOPS_REPOSITORY`/`GITOPS_BRANCH`, and update both Argo Applications' repoURL and
targetRevision. CI helpers remain in this source repository.

## Argo CD and first-run prerequisites

`gitops/argocd/policy-application.yaml` points to `gitops/policies/development`;
`demo-app-application.yaml` points to `gitops/applications/demo-app`. Both enable
automated sync, prune and selfHeal. Policy prune removes resources omitted by a
profile downgrade once Argo owns them. No namespace auto-creation option replaces
the explicit, labelled demo Namespace.

The initial policy desired state contains 13 exact approved development files.
They were bootstrapped offline from the locally available approved artifact:
aggregate SHA-256 `019d5af32e22b2fe422a28663cb3d7dfe3010f963eed980a4b0db920d4f5d583`,
source commit `9c51c23b60b6bfe3d34d9737f6a440e3309d0b76`. The local package passes the
existing integrity contract, but no Jenkins retrieval receipt was available.
Bootstrap provenance therefore records null job/build and explicitly does **not**
claim verified Jenkins origin. Run normal promotion from an explicitly selected
successful build before first operational reconciliation.

No verified prior demo image digest was available. The initial Deployment uses an
**all-zero SHA-256 bootstrap sentinel**, not a runnable image or a verified digest.
App CI rejects publishing that sentinel. Run App CI successfully to replace it
before registering/enabling the automated Demo Application. Do not sync the
bootstrap Deployment as an operational release.

Before the first real run:

- Review and commit these changes yourself; neither pipeline can use uncommitted
  local files. Provision the three trusted Jenkins jobs and required credentials.
- Preserve a successful full development Policy CI archive and select its build
  explicitly. Confirm the Jenkins canonical URL and artifact-reader permissions.
- Use the existing `ksp-tools` agent with Python/PyYAML, Git, Bash, Trivy, Crane
  and Cosign at repository-pinned versions. Git must support `GIT_CONFIG_COUNT`.
  Registry/Trivy DB/Sigstore/Jenkins/Git endpoints need network access and CA trust.
  No Kind, Docker daemon or BuildKit worker is needed for these flows.
- Configure branch/path filters and the Git writer. Run Policy Promotion with
  development + baseline and App CI before activating automated reconciliation.
- Argo CD must be installed/configured separately by the operator. Register the
  two Applications after reviewing desired state; give its project/controller the
  appropriate namespace and cluster-scoped Kyverno resource permissions.
  Existing Kyverno CRDs/controllers must be available. Neither Jenkins nor this
  refactor installs Argo CD or changes Kyverno installation.
- Reconcile policies before the first workload admission. Independent Applications
  do not guarantee cross-Application ordering; do not infer readiness from sync
  waves on separate Application objects. Check reconciliation through Argo CD.
- If policies previously installed outside Argo include standard/restricted groups,
  audit resource ownership and perform an explicit operator migration. Argo prune
  only removes resources it tracks; bootstrap baseline alone cannot guarantee that
  untracked legacy policies disappear. Jenkins performs no cluster cleanup.
- Provision `harbor-registry-credentials` in `ksp-demo` and Kyverno's namespace via
  existing secret management. Keep Harbor DNS, token-service URLs, certificates,
  node runtime trust and the policy/public signing key consistent.
- Preserve policy semantics. The existing IMG-002 allowlist contains
  `harbor.example.com`, while this demo uses `harbor-public:30003`. Development
  policies use their approved Audit/Warn behavior; stronger environments/profiles
  need policy-owner review and a new approved artifact if the registry contract
  changes. Baseline does not include every higher-profile signature policy;
  Jenkins Cosign verification remains mandatory regardless.
- Configure monitoring's reports, metrics, dashboards and alerts independently.
  `live-policies.py`, `delivery-reports.py`, `health-check.py` and
  `delivery-evidence.sh` remain diagnostic/test tools; none is called by the new
  GitOps pipelines. Their legacy operational paths are not CI stages.

A successful Jenkins publication proves CI gates and desired-state publication,
not successful reconciliation, admission, Pod readiness or observed compliance.

## Offline verification

```sh
python3 -B -m unittest discover -s jenkins/tests -v
python3 -B jenkins/scripts/test-approved-policies.py
```

The Jenkins regression suite uses local fixtures/tool doubles and temporary local
Git repositories. It tests immutable scalar editing, cumulative exact-byte policy
promotion, downgrade removal, invalid artifact rejection, Git publication conflicts,
credential handling, pipeline boundaries, and retained image/diagnostic behavior.
The approved-policy suite runs real offline Kyverno CLI checks when the CLI is
installed; it never creates a cluster. Also check Bash/Python syntax, parse GitOps
YAML and run `git diff --check`. No live Jenkins job, registry build/scan/push/sign,
cluster test, Argo installation or reconciliation is claimed by offline tests.
