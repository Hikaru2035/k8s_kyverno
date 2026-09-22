#!/usr/bin/env bash
# For the toolbox image / disposable Kind host, never the controller.
set -euo pipefail
source "$(dirname "$0")/common.sh"
[[ "$(uname -m)" == x86_64 ]] || { echo 'This demo toolchain targets linux/amd64'; exit 1; }
bin="${TOOLS_BIN:-/usr/local/bin}"
mkdir -p "$bin"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
fetch() { curl --fail --silent --show-error --location --retry 3 "$1" -o "$2"; }
k="$(version policy_engine.kyverno_cli.version)"
fetch "https://github.com/kyverno/kyverno/releases/download/v$k/kyverno-cli_v${k}_linux_x86_64.tar.gz" "$work/kyverno.tgz"
tar -xzf "$work/kyverno.tgz" -C "$work" kyverno
install -m 0755 "$work/kyverno" "$bin/kyverno"
k="$(version ci.helm.version)"
fetch "https://get.helm.sh/helm-v$k-linux-amd64.tar.gz" "$work/helm.tgz"
tar -xzf "$work/helm.tgz" -C "$work"
install -m 0755 "$work/linux-amd64/helm" "$bin/helm"
k="$(version ci.kind.version)"
fetch "https://kind.sigs.k8s.io/dl/v$k/kind-linux-amd64" "$bin/kind"
k="$(version jenkins.kubectl_version)"
fetch "https://dl.k8s.io/release/v$k/bin/linux/amd64/kubectl" "$bin/kubectl"
k="$(version image_security.cosign.version)"
fetch "https://github.com/sigstore/cosign/releases/download/v$k/cosign-linux-amd64" "$bin/cosign"
k="$(version jenkins.trivy_version)"
fetch "https://github.com/aquasecurity/trivy/releases/download/v$k/trivy_${k}_Linux-64bit.tar.gz" "$work/trivy.tgz"
tar -xzf "$work/trivy.tgz" -C "$work" trivy
install -m 0755 "$work/trivy" "$bin/trivy"
k="$(version jenkins.crane_version)"
fetch "https://github.com/google/go-containerregistry/releases/download/v$k/go-containerregistry_Linux_x86_64.tar.gz" "$work/crane.tgz"
tar -xzf "$work/crane.tgz" -C "$work" crane
install -m 0755 "$work/crane" "$bin/crane"
k="$(version jenkins.buildkit_version)"
fetch "https://github.com/moby/buildkit/releases/download/v$k/buildkit-v$k.linux-amd64.tar.gz" "$work/buildkit.tgz"
tar -xzf "$work/buildkit.tgz" -C "$work" bin/buildctl
install -m 0755 "$work/bin/buildctl" "$bin/buildctl"
chmod 0755 "$bin/kind" "$bin/kubectl" "$bin/cosign"
