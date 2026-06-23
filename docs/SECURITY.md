# NN Fund Management — Security

## Architecture

Security is layered in 3 tiers:

1. **Record Rules** — Odoo's `ir.rule` system for CRUD-level access
2. **Model-Level Checks** — `nn.security.mixin` for server-side enforcement
3. **State-Based Rules** — `security_hardening.xml` for workflow-specific access

## Groups

| Group | Access Level |
|---|---|
| Fund User | Read own records, create drafts |
| Finance User | Full CRUD on financial records, verify incoming funds |
| GM Approver | Approve step-1 allocations/requisitions/transfers |
| MD Approver | Approve step-2 allocations/requisitions/transfers |
| Fund Administrator | Full access including configuration |

## State-Based Rules

| Action | Permission |
|---|---|
| Approve allocation | Only GM/MD/Admin on submitted/pending_approval |
| Delete allocation | Only creator on drafts |
| Approve requisition | Only GM/MD/Admin on submitted/pending_approval |
| Approve transfer | Only GM/MD/Admin on submitted/pending_approval |
| Cancel bill | Only creator on drafts |
| Verify incoming | Only Finance/Admin on pending_verification |
| Write bank email parser | Only Admin |
| Ledger read-only | Non-administrators cannot modify |
| Approval history | Non-administrators cannot modify |
| Audit log | Non-administrators cannot modify |

## Dynamic Approval Security

The `nn.approval.matrix.line._user_can_approve()` method enforces that only authorized users (by group membership or direct assignment) can approve at each step. This is independent of the record-level rules and provides defense in depth.

## Company Isolation

Every financial model has a global record rule enforcing `[('company_id', '=', user.company_id.id)]`. Cross-company operations are prevented at the server level by `_enforce_same_company()`.

## API Security

- API keys are SHA-256 hashed at rest
- Rate limiting at 30 r/s per API key
- Company-scoped keys prevent cross-company access
- Expiring keys enforce rotation

## Production Security

- Docker secrets for credentials (never in env files committed to git)
- TLS 1.2/1.3 with HSTS preload (63072000s)
- CSP headers preventing XSS
- Rate limiting (login: 5r/m, API: 30r/s, web: 100r/s)
- Hidden file/credential blocking in nginx
- SSL termination at nginx (Odoo containers are not directly exposed)
