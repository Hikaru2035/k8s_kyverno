# Policy Configuration Model

Catalog thực thi gồm 29 base policy tại `policies/`. Tài liệu này mô tả cách ghép cấu hình:

```text
policies/<group>/<POLICY-ID>/*.yaml
  + profiles/<profile>/policy-ids.txt
  + environments/<environment>/parameters.env
  = artifacts/policies/<environment>/<profile>/
```

Nguồn sự thật:

- Policy logic và remediation: file policy.
- Membership/risk tier: `SECURITY-PROFILES.md` và `profiles/*/policy-ids.txt`.
- Environment values/mode/threshold: `environments/*/parameters.env`.
- Lifecycle và evidence: `POLICY-ROLLOUT-STRATEGY.md`.

Không chỉnh rendered artifact bằng tay. Mọi thay đổi phải thực hiện ở một trong ba lớp nguồn và render lại.

## Environment intent

| Environment | Default profile | Enforcement intent |
|---|---|---|
| Development | Standard | Validate/verify Audit; mutate/generate opt-in; failure default Ignore |
| Staging | Restricted | Critical và một số high-risk Enforce; failure critical Fail; chạy pilot/regression |
| Production | Restricted | Critical fail-closed; policy còn lại Enforce sau gate; rollback về Audit, không xóa policy |

## Commands

```bash
make policy-validate
make policy-render ENVIRONMENT=development
make policy-render ENVIRONMENT=staging
make policy-render ENVIRONMENT=production
```

Renderer output là release candidate, chưa tự apply cluster. Apply cần CI approval và server-side dry-run riêng.
