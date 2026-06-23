# NN Fund Management — Interview Guide

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Nginx (TLS 1.3, Rate Limit)             │
├─────────────────────────────────────────────────────────────┤
│               Odoo 18 Community (2+ replicas)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  nn.security.mixin  (10 methods, all models inherit)  │  │
│  │  nn.approval.matrix (unlimited levels, zero-code)     │  │
│  │  nn.fund.ledger     (14 types, immutable, posted)     │  │
│  │  nn.bank.email      (regex parser, dual dedup)        │  │
│  │  nn.ledger.reconciliation (7 checks, auto-block)      │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│              PostgreSQL 16 (SSL, tuned config)               │
│              Docker secrets (no env vars)                    │
│              9 cron jobs (validation, alerts, cleanup)       │
│              REST API (SHA-256 keys, rate limited)           │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Balance Calculation

### How It Works

Every financial operation posts an entry to `nn.fund.ledger` with exactly one non-zero side (debit XOR credit). All five fund account balances are computed in real-time by aggregating only entries with `state = 'posted'`.

### The 14 Transaction Types

| Type | Debit/Credit | Effect |
|------|-------------|--------|
| `incoming` | Debit | Increases balance |
| `allocation_hold` | Credit | Reduces available, increases held |
| `allocation_release` | Debit | Reverses hold, restores available |
| `allocation_approve` | Credit | Reduces available, increases assigned |
| `requisition_hold` | Credit | Reduces available, increases held |
| `requisition_release` | Debit | Reverses hold, restores available |
| `requisition_approved` | Credit | Reduces available, allocated to spend |
| `bill_posted` | Credit | Reduces available, increases spent |
| `bill_reversal` | Debit | Reverses spent, restores available |
| `transfer_hold` | Credit | Reduces source available |
| `transfer_release` | Debit | Reverses transfer hold |
| `transfer_approved_out` | Credit | Reduces source balance |
| `transfer_approved_in` | Debit | Increases destination balance |
| `adjustment` | Either | Manual correction (audit trail) |

### Balance Formulas (from `fund_account.py:166-246`)

```
current_balance = SUM(debits) - SUM(credits)  (all 14 types)

available_balance = incoming + transfer_approved_in
                    - held - assigned - spent
                    - transfer_approved_out - requisition_approved
```

Where:
- `held = allocation_hold + transfer_hold + requisition_hold - allocation_release - transfer_release - requisition_release` (min 0)
- `assigned = allocation_approve + transfer_approve`
- `spent = bill_posted - bill_reversal` (min 0)

### Why This Matters for Interviews

> "All balances are **computed, never stored**. This eliminates balance drift between transactions and the general ledger. The reconciliation engine independently verifies these computations by bypassing the `_compute_balances` method and aggregating raw ledger entries directly — if there's ever a discrepancy, the system detects it and blocks operations."

---

## 2. Double-Spending Prevention

### Problem

Two concurrent users submit transactions that together exceed the available balance. Without protection, both would see a sufficient balance, and the second would overspend.

### Three-Layer Defense

#### Layer 1: Ledger Holds

Before approval, money is held via hold-type ledger entries (credit). This immediately reduces the available balance seen by all other transactions. The hold is released on reject/cancel or converted to a permanent entry on approval.

```
On submit:         create hold entry (credit) → available drops
On reject:         create release entry (debit) → available restored
On approve:        create release + approve entries → atomic transition
```

#### Layer 2: SELECT FOR UPDATE NOWAIT

```python
# From security_mixin.py:170-173
self.env.cr.execute(
    "SELECT 1 FROM nn_fund_account WHERE id = %s FOR UPDATE NOWAIT",
    [account.id],
)
```

Before validating the balance, the system locks the account row in PostgreSQL. This prevents any concurrent transaction from modifying the same account simultaneously. If another transaction holds the lock, `NOWAIT` causes immediate failure rather than waiting for a deadlock.

#### Layer 3: Atomic Ledger Operations

Every state transition that affects balances creates all required ledger entries in a single database transaction. If any entry fails, the entire operation rolls back. For example, transfer approval creates 3 entries atomically:

```python
# single transaction:
entry_1 = create(transfer_release, debit=amount)      # release hold
entry_2 = create(transfer_approved_out, credit=amount) # reduce source
entry_3 = create(transfer_approved_in, debit=amount)   # increase dest
```

### Why This Matters for Interviews

> "Double-spending is prevented at three levels: ledger holds reserve money on submission, `SELECT FOR UPDATE NOWAIT` prevents concurrent phantom depletion, and atomic ledger creation ensures partial failures can't corrupt balances. The reconciliation engine then independently verifies every account nightly."

---

## 3. Approval Flow

### The Legacy System (Before)

Hardcoded states like `pending_gm` and `pending_md` in each model. Adding a new approval level required:
- New state field (`pending_board`)
- New group
- New permission checks in 3+ models
- New view filter
- New test cases

### The Dynamic Approval Matrix (After)

The entire approval flow is data-driven via two models:

**`nn.approval.matrix`** — Defines when a matrix applies:
- `request_type` (which Odoo model: allocation, requisition, transfer)
- `min_amount` / `max_amount` (amount range)
- `project_id` / `expense_head_id` (scoping)
- `effective_date` / `expiration_date` (temporal control)

**`nn.approval.matrix.line`** — Individual approval steps:
- `sequence` (order: 10, 20, 30...)
- `approval_group_id` (any `res.groups`)
- `user_id` (optional, for single-user steps)

### Matrix Selection Algorithm (4-Tier Fallback)

From `approval_matrix.py`:

```
1. Find matrix matching (request_type + project + expense_head + amount)
2. If not found: try (request_type + project + amount)  [expense head scoping]
3. If not found: try (request_type + expense_head + amount)  [project scoping]
4. If not found: try (request_type + amount)  [global]
5. If still not found: fall back to old nn.approval.rule
```

### Approval State Machine

```
Allocation:    draft → submitted → pending_approval* → approved → cancelled/rejected
Requisition:   draft → submitted → pending_approval* → approved → closed → cancelled/rejected
Transfer:      draft → submitted → pending_approval* → approved → cancelled/rejected
              ^^^ * cycles through all matrix lines, advancing current_matrix_line_id
```

The `action_approve` method on each model:
1. Checks `current_matrix_line_id._user_can_approve()`
2. Finds the current step's index in the ordered steps list
3. If a next step exists: advances `current_matrix_line_id` to it
4. If no next step: calls `_finalize_approval()` / `_execute_transfer()`

### Adding a New Approval Level

```xml
<record id="matrix_line_alloc_high_vp" model="nn.approval.matrix.line">
    <field name="matrix_id" ref="demo_matrix_alloc_high"/>
    <field name="sequence">35</field>  <!-- between MD (30) and Board (40) -->
    <field name="approval_group_id" ref="base.group_system"/>
    <field name="name">VP Approval</field>
</record>
```

No Python code, no module upgrade — just a new record.

### Why This Matters for Interviews

> "The approval engine is entirely data-driven. Approval levels are matrix lines — adding, removing, or reordering them requires no code changes. The 4-tier fallback allows fine-grained project or expense head scoping. This is a textbook example of the Strategy pattern implemented declaratively in Odoo."

---

## 4. Ledger Architecture

### Core Principle

Every financial event creates exactly one immutable record in `nn.fund.ledger` with:
- `debit` (> 0) XOR `credit` (> 0) — never both
- `transaction_type` — one of 14 predefined types
- `reference` — links to the source document number
- `reference_model` + `reference_id` — polymorphic link to source
- `state` — transitions from `posted` to `reversed`
- `company_id` — multi-company isolation

### Why Ledger, Not Direct Balance Updates

The constraint says:

> "Never update balances directly; all balances derived from ledger aggregates from 14 transaction types."

This means:
- No `fund_account.balance += amount` anywhere in the codebase
- All balance fields are `compute` methods, not stored
- The reconciliation engine independently verifies by aggregating raw ledger

### Fund Flow Diagram

```
                  ┌──────────────────────────────────────┐
                  │         Fund Account                  │
                  │  current_balance = ∑debits - ∑credits │
                  └──────┬───────────────────────────────┘
                         │
        ┌────────────────┼────────────────────┐
        ▼                ▼                    ▼
  ┌──────────┐    ┌──────────┐        ┌──────────────┐
  │ Incoming │    │Allocation│        │  Transfer     │
  │  debit   │    │  hold     │        │  hold/release │
  │  +1,000K │    │  -600K   │        │  -200K/+200K  │
  └──────────┘    └────┬─────┘        └──────┬───────┘
                       │                     │
                 ┌─────▼─────┐         ┌─────▼──────┐
                 │  Release  │         │ Approved   │
                 │  +600K    │         │ Out/In     │
                 └─────┬─────┘         │ -200K/+200K│
                       │               └────────────┘
                 ┌─────▼─────┐
                 │  Approve  │
                 │  -600K    │
                 └─────┬─────┘
                       │
                 ┌─────▼──────────────────┐
                 │   Requisition           │
                 │   hold/release/approved │
                 │   -150K/+150K           │
                 └─────┬──────────────────┘
                       │
                 ┌─────▼──────┐
                 │  Bill       │
                 │  posted     │
                 │  -100K      │
                 └────────────┘
```

### Why This Matters for Interviews

> "Every transaction is a first-class ledger entry. There's no hidden balance update. The ledger table is the single source of truth — you can audit any account by simply querying `SELECT * FROM nn_fund_ledger WHERE fund_account_id = X ORDER BY date`. The reconciliation engine independently recomputes all balances from this raw data."

---

## 5. Security Model

### Three-Tier Architecture

#### Tier 1: Record Rules (Database Level)

Every model has a global record rule enforcing multi-company isolation:

```xml
<field name="domain_force">[('company_id', 'in', company_ids)]</field>
```

These rules cannot be bypassed by Odoo ORM. They apply to read, write, create, and unlink operations.

#### Tier 2: Security Mixin (Model Level)

`nn.security.mixin` provides 10 methods inherited by every financial model:

| Method | Purpose | Defense Against |
|--------|---------|-----------------|
| `_check_company_permission` | Server-side company check | Cross-company access |
| `_check_state_transition` | Validate allowed transitions | Invalid workflow |
| `_check_write_permission` | Verify write access | Unauthorized edits |
| `_check_duplicate_field` | Detect duplicate values | Data corruption |
| `_check_duplicate_transaction` | Prevent double-posting | Financial duplicates |
| `_validate_positive_amount` | Amount > 0 | Invalid transactions |
| `_validate_available_balance` | Sufficient funds + row lock | Overspending |
| `_check_reconciliation_health` | Latest reconciliation check | Operating on bad data |
| `_check_user_is_approver` | Verify group membership | Unauthorized approval |
| `_check_approval_sequence` | Steps in correct order | Bypassing approvers |
| `_enforce_same_company` | All records same company | Cross-company operations |

#### Tier 3: State Machine Rules (Application Level)

Each model's `action_*` methods enforce state-based rules:

```python
def action_submit(self):
    if self.state != "draft":
        raise ValidationError(_("Only draft allocations can be submitted."))
```

### Operation Block on Reconciliation Critical

The `_check_reconciliation_health` method queries the latest `nn.ledger.reconciliation`. If `block_operations` is True, all financial operations are blocked:

```python
# security_mixin.py:195-217
@api.model
def _check_reconciliation_health(self):
    latest = self.env["nn.ledger.reconciliation"].search(
        [("company_id", "=", self.env.company.id)],
        order="date DESC, id DESC",
        limit=1,
    )
    if latest and latest.block_operations:
        raise ValidationError(
            _("Financial operations are currently blocked...")
        )
```

This is called from `_validate_available_balance`, which is the gateway method called by every financial operation (allocation submit, transfer submit, bill post, etc.).

### Permission Groups Hierarchy

```
base.group_user
  └── group_fund_user
       └── group_finance_user
            └── group_gm_approver
                 └── group_md_approver
                      └── group_fund_administrator
```

The hierarchy uses `implied_ids` — each group inherits all permissions of its parent. A GM can do everything a Finance user can do, and so on.

### Why This Matters for Interviews

> "Security is implemented at three independent layers. Even if a record rule is somehow misconfigured, the security mixin's server-side checks catch it. Even if the mixin check is somehow bypassed, the individual model methods validate state transitions. This is defense in depth — no single point of failure."

---

## Common Interview Questions

### Q: "How would you add a new transaction type?"

1. Add it to the `transaction_type` selection in `nn.fund.ledger`
2. Add its contribution to `_compute_balances` in `fund_account.py`
3. Add it to the reconciliation engine's `_check_account` in `ledger_reconciliation.py`
4. Update the 14-type documentation
5. Add test coverage for the new type in all balance scenarios

### Q: "How do you handle concurrency?"

PostgreSQL row-level locking with `SELECT FOR UPDATE NOWAIT`. Two concurrent submissions:
- T1: reads balance (1,000,000), locks account row
- T2: tries to read balance, gets `NOWAIT` error immediately
- T1: validates (500K < 1M OK), creates hold, commits
- T2: retries, reads balance (500K now), validates, proceeds or fails

### Q: "What happens if the database goes down mid-transaction?"

PostgreSQL's ACID compliance ensures atomicity. If the transaction creating 3 transfer entries fails after creating 2, all 3 are rolled back. The fund accounts remain consistent.

### Q: "How do you prevent API abuse?"

Three mechanisms:
- SHA-256 hashed API keys with rotation support
- Nginx rate limiting at 30 requests/second for API zone
- Rate limiter in `api/main.py` tracking requests per key per window

### Q: "How is the approval matrix different from Odoo's native approval?"

Odoo's native approval is tied to specific models and requires code for custom logic. The dynamic approval matrix is:
- Cross-model (allocation, requisition, transfer all use the same engine)
- Unlimited levels (not limited to 2-3 hardcoded states)
- Amount-range-aware (different approval chains for different values)
- Scoped by project/expense head (a specific project can require higher approval)
- Zero-code changes (new level = new record)

### Q: "How would you scale this to 10,000 concurrent users?"

- Stateless Odoo replicas behind Nginx load balancer (horizontal scaling)
- PostgreSQL connection pooling (Pgbouncer)
- Read replicas for reporting queries
- Cron jobs distributed across workers (different times, priority-based)
- REST API stateless by design — all auth via API key header
- Docker orchestration (Kubernetes or Docker Swarm) for auto-scaling

---

## Key Code References

| Concept | File | Lines |
|---------|------|-------|
| Balance computation | `models/fund_account.py` | 166-246 |
| Balance validation + row lock | `models/security_mixin.py` | 142-188 |
| Reconciliation health check | `models/security_mixin.py` | 194-217 |
| Allocation approval flow | `models/fund_allocation.py` | 376-449 |
| Transfer 3-entry execution | `models/fund_transfer.py` | 450-551 |
| Requisition billable tracking | `models/fund_requisition.py` | 202-215 |
| Bill overbilling prevention | `models/fund_bill.py` | 186-206 |
| Dynamic approval matrix | `models/approval_matrix.py` | (full file) |
| Reconciliation engine | `models/ledger_reconciliation.py` | (full file) |
| 14 transaction types | `models/fund_ledger.py` | (type selection) |
| Multi-company record rules | `security/record_rules.xml` | (full file) |
| Security groups hierarchy | `security/security_groups.xml` | (full file) |
