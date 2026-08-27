# Staging E2E runbook

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

Expected: all three namespaces have `ksp.io/environment=staging` and `ksp.io/profile=baseline`. These YAML exports are E2E/config evidence, not a disaster-recovery or etcd backup.

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
POD=$(kubectl -n kyverno get pod -l app.kubernetes.io/component=admission-controller -o jsonpath='{.items[0].metadata.name}')
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
