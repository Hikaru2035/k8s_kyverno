# Jenkins migration plan

The user-supplied architecture and acceptance criteria are the design brief.

1. Preserve GitLab's validation (including YAML references and render drift), Harbor
   authentication gate, 29-suite CLI/JUnit regression gate, rendered policy tests,
   seccomp Kind admission check, and always-collected reports. Extract the inline
   logic without changing policy inputs or expected results.
2. Run routine stages on ephemeral `ksp-tools` Kubernetes agents. Run Kind on an
   isolated `ksp-kind` host with a local container runtime; no host socket mounted
   into Jenkins and no privileged DinD. Use unique names, private kubeconfigs,
   shell traps and Jenkins finalization for cleanup.
3. Implement the delivery stages as shell commands with a small Python manifest
   helper. Use a remote, mTLS-authenticated BuildKit worker, scan its local image
   archive, push that exact archive, resolve and check the digest, sign and verify,
   then evaluate production Restricted policies before deployment. Verify live
   policy configuration and readiness, Pod admission, rollout and HTTP health.
4. Add official-chart Helm values, preflight rendering/evaluation, version pins,
   agent image build instructions, credential/plugin inventory and migration docs.
5. Verify aggregate failure behavior, malformed/mutable digest rejection, source
   manifest preservation, live-policy drift rejection, shell/YAML syntax and local
   Kyverno results. Render the actual chart. Do not claim unavailable runtime tests.

## Conflicts found before implementation

- IMG-002 allows harbor.example.com, registry.k8s.io and reg.kyverno.io, whereas
  IMG-004 and the requested delivery target use harbor-public:30003/ksp-test.
  Standard/Restricted delivery must fail; do not relabel to Baseline or alter policy.
- Jenkins is not a platform-exempt namespace. Upstream controller/agent images use
  tags and unapproved registries. Render and evaluate; do not add an exemption.
- GitLab's Kind job first applies the production bundle, deletes it, then tests
  POD-010 alone. Preserve that isolated test; add a full Baseline admission test
  with a compliant out-of-signature-scope bootstrap image, clearly distinguishing
  this from Harbor signature coverage supplied by CLI and delivery tests.
- GitLab installs Kyverno with one replica per controller and chart defaults,
  rather than the multi-node production Helm values. Preserve its CI settings.
- Existing Cosign policy disables transparency-log checking. Preserve that policy;
  delivery uses normal Cosign signing and verification with transparency logging.
- Harbor values expose a different externalURL from the requested hostname.
  DNS, certificate SANs and CA trust need operator verification.
- Existing monitoring modifications and local ignored private keys belong to the
  workspace. Do not read, copy, stage, or modify those private keys or edits.
