# Security Profiles: Baseline, Standard, Restricted

## 1. Mô hình

Profile là tập control tăng dần:

```text
Baseline ⊂ Standard ⊂ Restricted
```

- **Baseline:** chặn cấu hình có khả năng host/container escape rõ ràng, ít phá vỡ workload phổ biến.
- **Standard:** baseline cộng identity, resource hygiene và hardening phù hợp workload doanh nghiệp.
- **Restricted:** standard cộng immutable/signed image và Pod Security nghiêm ngặt.

Profile không tự quyết định Audit/Enforce; environment overlay quyết định mode. Production dùng mapping risk ở phần 3.

## 2. Mapping 30 source policy

KSP-META-003 is a common/bootstrap governance policy and is not counted in a security profile. Current source-of-truth counts are Common 1, Baseline 10, Standard 22, and Restricted 29. Runtime bundles are incremental: Standard adds 12 to Baseline and Restricted adds 7 to Standard.

| Policy ID | Baseline | Standard | Restricted | Risk rationale |
|---|:---:|:---:|:---:|---|
| KSP-POD-001 | — | ✓ | ✓ | root execution |
| KSP-POD-002 | ✓ | ✓ | ✓ | privileged/host compromise |
| KSP-POD-003 | — | ✓ | ✓ | privilege escalation |
| KSP-POD-004 | ✓ | ✓ | ✓ | host network exposure |
| KSP-POD-005 | ✓ | ✓ | ✓ | host process visibility |
| KSP-POD-006 | ✓ | ✓ | ✓ | host IPC access |
| KSP-POD-007 | ✓ | ✓ | ✓ | host filesystem access |
| KSP-POD-008 | — | — | ✓ | least Linux capability |
| KSP-POD-009 | — | — | ✓ | capability allowlist |
| KSP-POD-010 | — | — | ✓ | syscall restriction |
| KSP-POD-011 | — | ✓ | ✓ | filesystem persistence |
| KSP-POD-012 | — | ✓ | ✓ | development-only secure defaults |
| KSP-POD-013 | — | — | ✓ | explicit UID 0 |
| KSP-POD-014 | ✓ | ✓ | ✓ | direct node port exposure |
| KSP-IMG-001 | ✓ | ✓ | ✓ | mutable tag |
| KSP-IMG-002 | — | ✓ | ✓ | software supply-chain source |
| KSP-IMG-003 | — | — | ✓ | immutable image identity |
| KSP-IMG-004 | — | — | ✓ | signature/provenance |
| KSP-RES-001 | — | ✓ | ✓ | scheduling accuracy |
| KSP-RES-002 | — | ✓ | ✓ | memory capacity planning |
| KSP-RES-003 | — | — | ✓ | CPU governance |
| KSP-RES-004 | — | ✓ | ✓ | memory exhaustion |
| KSP-RES-005 | — | ✓ | ✓ | namespace blast radius |
| KSP-RES-006 | — | ✓ | ✓ | resource defaults |
| KSP-RES-007 | — | ✓ | ✓ | opted-in Namespace governance labels |
| KSP-META-001 | ✓ | ✓ | ✓ | application inventory |
| KSP-META-002 | — | ✓ | ✓ | accountability |
| KSP-META-003 | common | common | common | Namespace environment/profile governance |
| KSP-META-004 | ✓ | ✓ | ✓ | deterministic technical labels |
| KSP-NET-001 | ✓ | ✓ | ✓ | namespace network isolation |

## 3. Production enforcement by profile

| Severity/type | Baseline | Standard | Restricted |
|---|---|---|---|
| Critical validate | Enforce | Enforce | Enforce |
| High validate | Audit initially; Enforce after gate | Enforce after gate | Enforce after gate |
| Medium/Low validate | Audit | Audit/Enforce by risk owner | Enforce after gate except CPU limit may remain Audit |
| Mutate | deterministic labels only | labels; security mutation disabled in prod | labels; security mutation disabled in prod |
| Generate | selected controls | quota/limit/network opt-in | quota/limit/network opt-in |
| VerifyImages | not selected | not selected | Enforce only with production trust anchor |

Critical policy luôn dùng `failurePolicy: Fail` ở production. Enforce chỉ được bật sau rollout gate; profile selection không bỏ qua lifecycle.

## 4. Inheritance và conflict rules

- Restricted kế thừa toàn bộ Standard và Baseline; Standard kế thừa Baseline.
- Validate là nguồn sự thật production. KSP-POD-012 mutate không được dùng để che violation trong production.
- KSP-IMG-003 yêu cầu digest trước khi KSP-IMG-004 verify; cả hai dùng cùng registry parameter.
- ResourceQuota/LimitRange generate chỉ chạy namespace opt-in và phải thống nhất sizing.
- Default-deny NetworkPolicy phải được pilot cùng DNS/application allow policies; generate thành công không đồng nghĩa application healthy.

## 5. Profile selection

Profile is selected independently on each application Namespace with `ksp.io/profile=baseline|standard|restricted`; environment is `ksp.io/environment=dev|staging|production`. No one-to-one environment/profile mapping exists. Missing or invalid profile labels still receive Baseline controls and are reported by common KSP-META-003. Standard additions select Standard and Restricted namespaces; Restricted additions select only Restricted namespaces. Explicit platform namespace names are excluded from admission scope so an ordinary Namespace cannot bypass the framework by adding a label.
