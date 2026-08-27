# Expected results

Actions come from the rendered policy's environment-mode annotation; profile names never imply Audit, Warn, or Deny.

| ID | Profile | Policies | Path | Expected kubectl / state / report |
|---:|---|---|---|---|
| 01 | common | KSP-META-003 | background | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 02 | common | KSP-META-003 | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 03 | common | KSP-META-003 | CREATE | succeeds with Audit/Warn; PolicyReport violation |
| 04 | common | KSP-META-003 | CREATE | succeeds with Audit/Warn; PolicyReport violation |
| 05 | common | KSP-META-003 | CREATE | succeeds with Audit/Warn; PolicyReport violation |
| 06 | common | KSP-META-003 | CREATE | succeeds with Audit/Warn; PolicyReport violation |
| 07 | common | KSP-META-003 | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 08 | baseline | KSP-META-003 | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 09 | baseline | KSP-IMG-001,KSP-META-001,KSP-META-004 | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 10 | baseline | KSP-IMG-001 | CREATE | denied on admission (11 must be created before policy for background result) |
| 11 | baseline | KSP-IMG-001 | background | denied on admission (11 must be created before policy for background result) |
| 12 | standard | KSP-META-003,KSP-IMG-002,KSP-POD-001 | UPDATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 13 | standard | KSP-IMG-002,KSP-POD-001,KSP-POD-003,KSP-RES-001,KSP-RES-002,KSP-RES-004 | CREATE | each participating runtime policy follows its rendered annotation; capture warning/deny and PolicyReport; inspect generated/mutated objects |
| 14 | standard | Baseline+Standard policy IDs | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 15 | restricted | KSP-META-003 plus Baseline+Standard+Restricted | UPDATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 16 | restricted | KSP-IMG-001,KSP-IMG-002,KSP-IMG-003,KSP-POD-001,KSP-POD-003,KSP-POD-008..013,KSP-RES-001..004 | CREATE | kubectl succeeds; inspect actual cluster state and PolicyReport |
| 17 | restricted | KSP-IMG-001..004,KSP-POD-001..014,KSP-RES-001..007,KSP-NET-001,KSP-META-004 | CREATE | each participating runtime policy follows its rendered annotation; capture warning/deny and PolicyReport; inspect generated/mutated objects |
| 18 | restricted | active validating policy set | CREATE | each participating runtime policy follows its rendered annotation; capture warning/deny and PolicyReport; inspect generated/mutated objects |

For scenarios 11 and 17, verify PolicyReports. For mutate/generate policies in 17, inspect the patched object plus ResourceQuota, LimitRange, and NetworkPolicy rather than relying on the kubectl exit code. Scenario 18 validates Kyverno service availability only and does not claim control-plane HA.
