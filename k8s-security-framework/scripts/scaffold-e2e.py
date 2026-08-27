#!/usr/bin/env python3
"""Create identical, environment-parameterized E2E scenarios and documentation."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
ENVS={"development":"dev","staging":"staging","production":"production"}
SCENARIOS={
1:"preexisting namespaces for META-003 background evaluation",2:"valid Namespace labels",3:"missing environment",4:"invalid environment",5:"missing profile",6:"invalid profile",7:"independent environment/profile",8:"three Baseline business namespaces",9:"Baseline-compliant workload",10:"intentional Baseline latest-tag violation",11:"pre-policy non-compliant workload for background scan",12:"promote canary to Standard while retaining Baseline control",13:"Standard violation and remediation",14:"replicated Deployment and Service availability",15:"promote canary to Restricted",16:"Restricted-compliant hardened workload",17:"Restricted composite violation and generated-resource checks",18:"Kyverno admission-controller failure/HA evidence"}

def ns(name, env, profile="baseline", env_key=True, profile_key=True):
    labels=[]
    if env_key: labels.append(f"    ksp.io/environment: {env}")
    if profile_key: labels.append(f"    ksp.io/profile: {profile}")
    return f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {name}\n  labels:\n"+"\n".join(labels)+"\n"

def deploy(name, namespace, image="registry.k8s.io/pause:3.10", replicas=1, hardened=False):
    security="""      securityContext:\n        runAsNonRoot: true\n        seccompProfile: {type: RuntimeDefault}\n""" if hardened else ""
    container="""        securityContext:\n          allowPrivilegeEscalation: false\n          capabilities: {drop: [ALL]}\n          readOnlyRootFilesystem: true\n          runAsNonRoot: true\n          runAsUser: 65532\n        resources:\n          requests: {cpu: 10m, memory: 16Mi}\n          limits: {cpu: 100m, memory: 64Mi}\n""" if hardened else ""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: {namespace}
  labels: {{app.kubernetes.io/name: {name}, policies.ksp.io/owner: e2e}}
spec:
  replicas: {replicas}
  selector: {{matchLabels: {{app.kubernetes.io/name: {name}}}}}
  template:
    metadata: {{labels: {{app.kubernetes.io/name: {name}}}}}
    spec:
{security}      containers:
      - name: app
        image: {image}
{container}"""

def content(i, env):
    e=ENVS[env]; a="e2e-ksp-alpha"; b="e2e-ksp-beta"; c="e2e-ksp-canary"
    if i==1: return "---\n".join(ns(x,e) for x in (a,b,c))
    if i==2: return ns("e2e-ksp-valid",e,"standard")
    if i==3: return ns("e2e-ksp-missing-environment",e,"baseline",False,True)
    if i==4: return ns("e2e-ksp-invalid-environment","qa","baseline")
    if i==5: return ns("e2e-ksp-missing-profile",e,"baseline",True,False)
    if i==6: return ns("e2e-ksp-invalid-profile",e,"hardened")
    if i==7: return ns("e2e-ksp-independent-profile",e,"restricted")
    if i==8: return "---\n".join(ns(x,e) for x in (a,b,c))
    if i==9: return deploy("e2e-ksp-baseline-ok",a,hardened=True)
    if i==10: return deploy("e2e-ksp-baseline-violation",a,"nginx:latest")
    if i==11: return deploy("e2e-ksp-existing-violation",b,"nginx:latest")
    if i==12: return ns(c,e,"standard")+"---\n"+ns(a,e,"baseline")
    if i==13: return deploy("e2e-ksp-standard-remediation",c,"nginx:latest")+"---\n"+deploy("e2e-ksp-standard-fixed",c,hardened=True)
    if i==14: return deploy("e2e-ksp-ha-app",c,replicas=3,hardened=True)+"---\n"+f"apiVersion: v1\nkind: Service\nmetadata: {{name: e2e-ksp-ha-app, namespace: {c}}}\nspec: {{selector: {{app.kubernetes.io/name: e2e-ksp-ha-app}}, ports: [{{port: 80, targetPort: 8080}}]}}\n"
    if i==15: return ns(c,e,"restricted")
    if i==16: return deploy("e2e-ksp-restricted-ok",c,"registry.k8s.io/pause@sha256:58e0d1ca5295e09e21b94244a05a8dd43546cf6a347afbf19cdd79f58835c4c2",hardened=True)
    if i==17: return deploy("e2e-ksp-restricted-composite-violation",c,"nginx:latest")+"---\n"+f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: e2e-ksp-generated-check\n  labels:\n    ksp.io/environment: {e}\n    ksp.io/profile: restricted\n    policies.ksp.io/generate-network-baseline: enabled\n    policies.ksp.io/generate-resource-governance: enabled\n    policies.ksp.io/environment: {e}\n    policies.ksp.io/quota-class: small\n"
    return deploy("e2e-ksp-ha-admission-check",c,hardened=True)+"---\n"+deploy("e2e-ksp-ha-deny-check",c,"nginx:latest")

def runbook(env, env_value):
    return f"""# {env.title()} E2E runbook

Run from this directory. Set `EVIDENCE=evidence/$(date -u +%Y%m%dT%H%M%SZ)` and `mkdir -p "$EVIDENCE"`. Every `tee` output below is evidence; do not store kubeconfigs, tokens, certificates, or private keys.

## 1. Preflight

Purpose: prove nodes, Kyverno replicas, admission path, and policy APIs are ready.

```sh
kubectl get nodes -o wide | tee "$EVIDENCE/nodes.txt"
kubectl -n kyverno get pods -o wide | tee "$EVIDENCE/kyverno-pods.txt"
kubectl -n kyverno get svc,endpoints,endpointslices | tee "$EVIDENCE/kyverno-network.txt"
kubectl api-resources | grep -E 'validatingpolicies|mutatingpolicies|generatingpolicies|policyreports' | tee "$EVIDENCE/policy-apis.txt"
helm -n kyverno get values kyverno -a > "$EVIDENCE/kyverno-helm-values.yaml"
```

Expected: all nodes and Kyverno replicas Ready, `kyverno-svc` has endpoints, and all required policy APIs are listed.

## 2. Initial state and pre-policy evidence

Purpose: create the three Baseline namespaces before common policy so Scenario 01 can prove background evaluation.

```sh
kubectl apply -f tests/scenario-01.yaml | tee "$EVIDENCE/01-create-preexisting.txt"
kubectl apply -f tests/scenario-11.yaml | tee "$EVIDENCE/11-create-before-policy.txt"
kubectl get ns e2e-ksp-alpha e2e-ksp-beta e2e-ksp-canary -o yaml > "$EVIDENCE/01-namespaces.yaml"
kubectl get validatingpolicies,mutatingpolicies,generatingpolicies -A -o yaml > "$EVIDENCE/pre-common-policies.yaml"
kubectl get policyreports -A -o yaml > "$EVIDENCE/pre-common-policyreports.yaml"
kubectl get deploy,sts,ds,job,cronjob -A -o yaml > "$EVIDENCE/pre-common-workloads.yaml"
```

Expected: all three namespaces have `ksp.io/environment={env_value}` and `ksp.io/profile=baseline`. These YAML exports are E2E/config evidence, not a disaster-recovery or etcd backup.

## 3. Common and Baseline gate

```sh
kubectl apply -f policies/common/ | tee "$EVIDENCE/common-apply.txt"
kubectl apply -f policies/baseline/ | tee "$EVIDENCE/baseline-apply.txt"
kubectl get validatingpolicies,mutatingpolicies,generatingpolicies -o wide | tee "$EVIDENCE/baseline-active.txt"
for n in 02 03 04 05 06 07 08 09 10; do kubectl apply --dry-run=server -f "tests/scenario-$n.yaml" 2>&1 | tee "$EVIDENCE/$n.txt"; done
kubectl get policyreports -A -o yaml > "$EVIDENCE/baseline-policyreports.yaml"
kubectl -n kyverno logs -l app.kubernetes.io/component=admission-controller --all-containers --since=15m > "$EVIDENCE/baseline-kyverno.log"
```

Expected: valid objects succeed; invalid objects follow each rendered policy's action in `EXPECTED-RESULTS.md`; Scenario 11 appears in a PolicyReport when background evaluation is enabled.

## 4. Standard promotion

Purpose: preserve pre-promotion state, install only Standard additions, and prove the Baseline control namespace is not selected by them.

```sh
kubectl get validatingpolicies,mutatingpolicies,generatingpolicies -o yaml > "$EVIDENCE/pre-standard-policies.yaml"
kubectl get ns e2e-ksp-alpha e2e-ksp-beta e2e-ksp-canary -o yaml > "$EVIDENCE/pre-standard-namespaces.yaml"
kubectl get all -n e2e-ksp-canary -o yaml > "$EVIDENCE/pre-standard-workloads.yaml"
kubectl get policyreports -A -o yaml > "$EVIDENCE/pre-standard-policyreports.yaml"
kubectl apply -f policies/standard/ | tee "$EVIDENCE/standard-apply.txt"
kubectl apply -f tests/scenario-12.yaml | tee "$EVIDENCE/12-promote.txt"
kubectl apply --dry-run=server -f tests/scenario-13.yaml 2>&1 | tee "$EVIDENCE/13-violate-remediate.txt"
kubectl apply -f tests/scenario-14.yaml | tee "$EVIDENCE/14-ha-app.txt"
kubectl -n e2e-ksp-canary rollout status deploy/e2e-ksp-ha-app
kubectl -n e2e-ksp-canary get pods,endpoints,endpointslices -o wide | tee "$EVIDENCE/14-availability.txt"
```

Expected: canary becomes Standard, alpha remains Baseline, remediation succeeds, three replicas become Ready, and the Service has endpoints.

## 5. Restricted promotion

```sh
kubectl get validatingpolicies,mutatingpolicies,generatingpolicies -o yaml > "$EVIDENCE/pre-restricted-policies.yaml"
kubectl get ns e2e-ksp-alpha e2e-ksp-beta e2e-ksp-canary -o yaml > "$EVIDENCE/pre-restricted-namespaces.yaml"
kubectl get all -n e2e-ksp-canary -o yaml > "$EVIDENCE/pre-restricted-workloads.yaml"
kubectl get policyreports -A -o yaml > "$EVIDENCE/pre-restricted-policyreports.yaml"
kubectl apply -f policies/restricted/ | tee "$EVIDENCE/restricted-apply.txt"
kubectl apply -f tests/scenario-15.yaml | tee "$EVIDENCE/15-promote.txt"
kubectl apply --dry-run=server -f tests/scenario-16.yaml 2>&1 | tee "$EVIDENCE/16-hardened.txt"
kubectl apply -f tests/scenario-17.yaml 2>&1 | tee "$EVIDENCE/17-composite.txt"
kubectl get networkpolicy,resourcequota,limitrange -A -o yaml > "$EVIDENCE/17-generated.yaml"
kubectl get policyreports -A -o yaml > "$EVIDENCE/restricted-policyreports.yaml"
```

Expected: canary receives Baseline + Standard + Restricted; alpha remains a Baseline control. Generated and mutated state is inspected explicitly. Promotion is an E2E scenario, not a rule that every enterprise workload must become Restricted.

## 6. Kyverno failure/HA scenario

Purpose: test admission-controller replica failure without claiming Kubernetes control-plane HA.

```sh
POD=$(kubectl -n kyverno get pod -l app.kubernetes.io/component=admission-controller -o jsonpath='{{.items[0].metadata.name}}')
kubectl -n kyverno delete pod "$POD" | tee "$EVIDENCE/18-delete-one-pod.txt"
kubectl -n kyverno wait --for=condition=Ready pod -l app.kubernetes.io/component=admission-controller --timeout=180s
kubectl -n kyverno get pods,endpoints,endpointslices -o wide | tee "$EVIDENCE/18-after-failure.txt"
kubectl apply --dry-run=server -f tests/scenario-18.yaml 2>&1 | tee "$EVIDENCE/18-admission.txt"
```

Expected: remaining/recreated replicas are Ready, service endpoints remain, compliant CREATE succeeds, and the violating CREATE/UPDATE receives the rendered action.

## 7. Cleanup

```sh
kubectl delete ns e2e-ksp-alpha e2e-ksp-beta e2e-ksp-canary e2e-ksp-valid e2e-ksp-independent-profile e2e-ksp-generated-check --ignore-not-found
kubectl delete -f policies/restricted/ --ignore-not-found
kubectl delete -f policies/standard/ --ignore-not-found
kubectl delete -f policies/baseline/ --ignore-not-found
kubectl delete -f policies/common/ --ignore-not-found
```

Expected: only E2E namespaces and policies from this bundle are removed; no cluster-wide destructive cleanup is used.
"""

def main():
    envs=sys.argv[1:] or list(ENVS)
    for env in envs:
        if env not in ENVS: raise SystemExit(f"unknown environment {env}")
        out=ROOT/"e2e_env"/env; tests=out/"tests"; evidence=out/"evidence"
        tests.mkdir(parents=True,exist_ok=True); evidence.mkdir(parents=True,exist_ok=True)
        (evidence/".gitkeep").touch()
        for i,title in SCENARIOS.items():
            (tests/f"scenario-{i:02d}.yaml").write_text(f"# Scenario {i:02d}: {title}\n"+content(i,env))
        (out/"platform-namespaces.yaml").write_text("# Renderer source of truth for explicit platform exclusions.\nplatformNamespaces:\n"+"".join(f"- {x}\n" for x in ['default','kube-system','kube-public','kube-node-lease','kyverno','calico-system','tigera-operator']))
        mode={"development":"dev-mode","staging":"staging-mode","production":"prod-mode"}[env]
        readme=f"""# {env.title()} E2E bundle

This directory is a self-contained executable bundle for one real `{env}` cluster. Copy this directory alone, then follow `RUNBOOK.md`; it has no symlinks or runtime dependencies on another environment directory.

`policies/common/` contains KSP-META-003. `baseline/` contains the 10 minimum-profile policies; `standard/` and `restricted/` contain only set-difference additions. Runtime actions are rendered from `policies.ksp.io/{mode}`, never inferred from the profile. `platform-namespaces.yaml` documents the explicit, name-based exemptions; an application label cannot create an exemption.

The repository's existing `environments/` tree remains the general parameter/configuration layer. `e2e_env/` contains executable cluster-specific E2E bundles.
"""
        (out/"README.md").write_text(readme)
        rows=[]
        involved={
            1:"KSP-META-003",2:"KSP-META-003",3:"KSP-META-003",4:"KSP-META-003",5:"KSP-META-003",6:"KSP-META-003",7:"KSP-META-003",8:"KSP-META-003",
            9:"KSP-IMG-001,KSP-META-001,KSP-META-004",10:"KSP-IMG-001",11:"KSP-IMG-001",12:"KSP-META-003,KSP-IMG-002,KSP-POD-001",13:"KSP-IMG-002,KSP-POD-001,KSP-POD-003,KSP-RES-001,KSP-RES-002,KSP-RES-004",14:"Baseline+Standard policy IDs",15:"KSP-META-003 plus Baseline+Standard+Restricted",16:"KSP-IMG-001,KSP-IMG-002,KSP-IMG-003,KSP-POD-001,KSP-POD-003,KSP-POD-008..013,KSP-RES-001..004",17:"KSP-IMG-001..004,KSP-POD-001..014,KSP-RES-001..007,KSP-NET-001,KSP-META-004",18:"active validating policy set"}
        for i,title in SCENARIOS.items():
            profile="common" if i<8 else "baseline" if i<12 else "standard" if i<15 else "restricted"
            op="background" if i in (1,11) else "UPDATE" if i in (12,15) else "CREATE"
            policy=involved[i]
            if i in (3,4,5,6): expected={"development":"succeeds with Audit/Warn; PolicyReport violation","staging":"succeeds with Audit/Warn; PolicyReport violation","production":"denied by META-003; PolicyReport/admission evidence"}[env]
            elif i in (10,11): expected={"development":"succeeds with Audit/Warn; PolicyReport violation","staging":"denied on admission (11 must be created before policy for background result)","production":"denied on admission (11 must be created before policy for background result)"}[env]
            elif i in (13,17,18): expected="each participating runtime policy follows its rendered annotation; capture warning/deny and PolicyReport; inspect generated/mutated objects"
            else: expected="kubectl succeeds; inspect actual cluster state and PolicyReport"
            rows.append(f"| {i:02d} | {profile} | {policy} | {op} | {expected} |")
        expected_doc="# Expected results\n\nActions come from the rendered policy's environment-mode annotation; profile names never imply Audit, Warn, or Deny.\n\n| ID | Profile | Policies | Path | Expected kubectl / state / report |\n|---:|---|---|---|---|\n"+"\n".join(rows)+"\n\nFor scenarios 11 and 17, verify PolicyReports. For mutate/generate policies in 17, inspect the patched object plus ResourceQuota, LimitRange, and NetworkPolicy rather than relying on the kubectl exit code. Scenario 18 validates Kyverno service availability only and does not claim control-plane HA.\n"
        (out/"EXPECTED-RESULTS.md").write_text(expected_doc)
        (out/"RUNBOOK.md").write_text(runbook(env, ENVS[env]))
    print("scaffolded: "+", ".join(envs))
if __name__=="__main__": main()
