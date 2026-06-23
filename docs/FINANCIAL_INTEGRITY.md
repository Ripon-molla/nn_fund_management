# Financial Integrity Architecture

## Overview

The NN Fund Management system implements 10 layers of financial integrity protection.
Every protection is enforced at the **server level** (Python/Odoo ORM) and supplemented
by **database constraints** (SQL) and **record rules** (security). No protection relies
solely on UI-level controls.

---

## 1. Ledger Immutability

### Principle
Once a ledger entry is **posted**, it becomes **immutable** — it cannot be edited,
deleted, or reverted to draft. Once it's **reversed**, it becomes completely frozen.

### Implementation
- **`models/fund_ledger.py::write()`** (line 262): On posted entries, only `state`
  changes to `"reversed"` are allowed. All other field modifications raise `UserError`.
- **`models/fund_ledger.py::write()`** (line 272): Reversed entries reject **all** writes.
- **`models/fund_ledger.py::unlink()`** (line 274): Posted and reversed entries
  cannot be deleted. Only draft entries can be cleaned up.
- **SQL constraints**: `check_debit_credit_not_both_positive` and
  `check_debit_credit_not_both_zero` ensure every entry has exactly one direction
  with a non-zero amount.

### Enforcement points
- Every `fund_ledger.create()` goes through `write()` for state transitions.
- `action_reverse()` transitions via `write()`, which validates reversal rules.
- Access controls via `rule_nn_fund_ledger_readonly` make ledger read-only
  for non-administrators at the ORM level.

---

## 2. Approval Idempotency

### Principle
A user cannot approve the same request at the same approval step more than once.
This prevents double-counting approvals when a user accidentally clicks "Approve" twice.

### Implementation
- **`models/security_mixin.py::_check_approval_idempotency()`** (line 137): Checks
  `nn.approval.history` for an existing approval by the same user for the same
  request at the same matrix line. Raises `ValidationError` on duplicate.
- Called from every `action_approve()` method:
  - `models/fund_allocation.py::action_approve()` (line 425)
  - `models/fund_transfer.py::action_approve()` (line 557)
  - `models/fund_requisition.py::action_approve()` (line 370)

### Key detail
The check uses `matrix_line_id` to scope the idempotency to the current step.
A user who approved at step 1 (GM) can still approve at step 2 (MD) — each step
is independent.

---

## 3. Transaction Idempotency

### Principle
Every ledger entry has a unique `transaction_uuid`. If the same UUID is used twice,
the database constraint rejects the duplicate. This prevents double-posting of
the same financial transaction.

### Implementation
- **`models/fund_ledger.py::transaction_uuid`** (line 113): Auto-generated UUID4
  on creation via `default=lambda self: str(uuid.uuid4())`.
- **SQL constraint**: `UNIQUE(transaction_uuid)` at database level.
- **`security_mixin.py::_enforce_transaction_idempotency()`** (line 161):
  Programmatic check before creating ledger entries (defense in depth).

### How UUIDs flow
- Every `nn.fund.ledger.create()` automatically sets `transaction_uuid`.
- Reversal entries get a **new** UUID (not the original), ensuring unique identity.
- The UUID is immutable (`readonly=True, copy=False`).

---

## 4. Concurrency Protection (Row-Level Locking)

### Principle
Before any financial operation that modifies an account balance, the system
acquires a **row-level exclusive lock** (`SELECT FOR UPDATE NOWAIT`) on the
account record. This prevents two concurrent transactions from simultaneously
reading the same balance and both proceeding with insufficient funds.

### Implementation
- **`models/security_mixin.py::_acquire_row_lock()`** (line 46): Executes
  `SELECT id FROM nn_fund_account WHERE id = %s FOR UPDATE NOWAIT`.
- Called from every financial action:
  - `_validate_available_balance()` — allocations, transfers, requisitions, bills
  - `action_confirm()` — incoming funds
  - `action_reverse()` — incoming fund reversals
  - `_execute_transfer()` — locks both source AND destination accounts
- `NOWAIT` mode means the request immediately fails if another transaction holds
  the lock, rather than waiting indefinitely.

### Why FOR UPDATE NOWAIT
In multi-worker Odoo deployments, two workers could read the same available
balance simultaneously. Without locking, both would see sufficient funds and
create ledger entries, resulting in **overdraft**. The lock serializes access
to the account row.

---

## 5. Balance Validation

### Principle
Before every financial action that consumes funds, the system validates that
the account has sufficient available balance. This validation happens AFTER
acquiring the row lock, ensuring the balance hasn't changed since it was read.

### Implementation
- **`models/security_mixin.py::_validate_available_balance()`** (line 75):
  Centralized method that:
  1. Checks `_check_reconciliation_health()` — blocks operations if reconciliation
     detected critical imbalance
  2. Acquires row lock via `_acquire_row_lock()`
  3. Re-reads balance (now protected from concurrent modification)
  4. Validates `available >= required`
  5. Raises `ValidationError` with detailed message

### Enforcement points
- `fund_allocation.action_submit()` — validates hold amount
- `fund_transfer.action_submit()` — validates hold amount
- `fund_requisition.action_submit()` — validates hold amount
- `incoming_fund.action_reverse()` — validates reversal amount
- `fund_bill.action_post()` — validates remaining billable (separate check)

---

## 6. Reversal Integrity

### Principle
A reversal must be the **exact mirror image** of the original entry. The net
financial impact of creating a reversal must be **zero** — it must neither
create nor destroy money.

### Implementation
- **`models/fund_ledger.py::_verify_reversal_integrity()`** (line 293):
  Validates four conditions:
  1. `original.debit == reversal.credit` (mirror image)
  2. `original.credit == reversal.debit` (mirror image)
  3. Same `fund_account_id` (can't reverse across accounts)
  4. `(orig_debit - orig_credit) + (rev_debit - rev_credit) == 0` (net zero)

- **`models/fund_ledger.py::action_reverse()`** (line 283): Creates reversal entry
  with swapped debit/credit, then calls `_verify_reversal_integrity()`.

- **`models/incoming_fund.py::action_reverse()`** (line 248): Calls
  `_verify_reversal_integrity()` after creating the reversal ledger entry.

### Key behavior
- Reversal creates a NEW posted entry, not a modification of the original.
- Original entry transitions to `"reversed"` state (immutable thereafter).
- Both entries appear in the ledger, providing a complete audit trail.
- Balance computation correctly nets them out: `incoming 1000 - reversal 1000 = 0`.

---

## 7. Audit Immutability

### Principle
Audit log records are **immutable by design**. Once created, they cannot be
modified or deleted under any circumstances. This ensures a tamper-proof
audit trail for regulatory compliance.

### Implementation
- **`models/audit_log.py::write()`** (line 144): Raises `UserError` on any
  modification attempt.
- **`models/audit_log.py::unlink()`** (line 152): Raises `UserError` on any
  deletion attempt.
- **Record rules**: `rule_nn_audit_log_readonly` makes audit log read-only
  for non-administrators at the ORM level (defense in depth).
- **Access controls**: Only `group_fund_administrator` has write/create/unlink
  permissions on `nn.audit.log`.

### Why this matters
Audit trails are legal evidence. In many jurisdictions, financial records
must be retained in their original form for 7+ years. Modifiable audit logs
would violate regulatory requirements and compromise the integrity of the
entire system.

---

## 8. API Replay Protection

### Principle
State-changing API requests are protected against **replay attacks** via
idempotency keys. Each request must include a unique `Idempotency-Key` header.
If the same key is used twice, the server rejects the duplicate.

### Implementation
- **`api/main.py::ApiIdempotencyKey`** (line 215): Model storing used keys with
  24-hour expiration. Unique constraint on `idempotency_key`.
- **`api/main.py::check_and_create()`** (line 248): Atomically checks existence
  and creates a new record. If exists, raises `ValidationError`.
- **`controllers/main.py::api_approval_action()`** (line 382): Checks
  `Idempotency-Key` header before executing any approval action.
- **Cleanup cron**: `cron_clean_idempotency_keys` runs daily to purge expired keys.

### Client usage
```
POST /api/v1/approvals/allocation/42/approve
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
```

### Multi-worker safety
The unique SQL constraint on `idempotency_key` ensures that even if two workers
process the same key simultaneously, only one succeeds (the other gets a
database-level unique constraint violation).

---

## 9. Financial Consistency Validation

### Principle
A comprehensive cross-check that validates **all financial relationships** across
the system. This is a read-only diagnostic that detects anomalies without
modifying any data.

### Implementation
- **`models/security_mixin.py::_check_financial_consistency()`** (line 174):
  Performs 6 independent checks:
  1. **Balance cross-check**: Compares stored computed balances against
     ledger-derived aggregates for every account
  2. **Orphan detection**: Finds ledger entries whose source record doesn't exist
  3. **Duplicate detection**: Finds ledger entries with identical
     (reference, type, account, debit, credit) combos
  4. **Negative balance**: Flags accounts with negative current balance
  5. **Missing entries**: Checks that approved records have corresponding ledger entries
  6. **Transfer balance**: Verifies transfer out == transfer in for every approved transfer

- **`models/fund_account.py::action_check_financial_consistency()`** (line 261):
  UI-triggerable action that runs the check on a specific account.

### Violation reporting
All violations are logged to the audit trail via `_log_consistency_violations()`.
The method returns a structured result with violation count and details.

---

## 10. Emergency Recovery Procedures

### Principle
Administrator-only tools to recover from exceptional situations without
violating financial integrity. All recovery actions are audited.

### Implementation
- **`models/security_mixin.py::_emergency_recover_balance()`** (line 327):
  Recomputes and corrects stored balance fields from ledger data. Does NOT
  create or destroy money — only fixes display values.
- **`models/security_mixin.py::_emergency_reverse_transaction()`** (line 358):
  Creates a reversal entry for any posted ledger entry. Requires:
  - Fund Administrator group membership
  - Detailed reason (minimum 10 characters)
  - All standard reversal integrity checks still apply
- **`models/security_mixin.py::_emergency_get_recovery_report()`** (line 397):
  Generates a comprehensive snapshot of account state including all entries,
  balance comparisons, and anomaly detection.
- **`models/ledger_reconciliation.py::action_unblock_operations()`** (line 597):
  Allows administrators to unblock financial operations after reconciliation
  issues are resolved.
- **`models/ledger_reconciliation.py::action_run_reconciliation()`** (line 165):
  Re-runs reconciliation to validate that issues have been corrected.

### Safety guarantees
1. Emergency recovery never directly modifies ledger entries.
2. Emergency reversals go through the same `_verify_reversal_integrity()` check.
3. All recovery actions are logged to the immutable audit trail.
4. Only Fund Administrators (a system-configurable group) can execute recovery.

---

## Summary: Protection Matrix

| # | Protection | Model Level | DB Level | Security Level |
|---|-----------|-------------|----------|----------------|
| 1 | Ledger Immutability | `write()`/`unlink()` override | SQL constraints | Record rules |
| 2 | Approval Idempotency | `_check_approval_idempotency()` | — | — |
| 3 | Transaction Idempotency | `transaction_uuid` auto-generate | `UNIQUE(transaction_uuid)` | — |
| 4 | Concurrency Protection | `SELECT FOR UPDATE NOWAIT` | — | — |
| 5 | Balance Validation | `_validate_available_balance()` | — | — |
| 6 | Reversal Integrity | `_verify_reversal_integrity()` | — | — |
| 7 | Audit Immutability | `write()`/`unlink()` override | — | Record rules + ACLs |
| 8 | API Replay Protection | `check_and_create()` | `UNIQUE(idempotency_key)` | ACLs |
| 9 | Financial Consistency | `_check_financial_consistency()` | — | — |
| 10 | Emergency Recovery | Admin-guarded methods | — | Group check |

Each protection operates at **minimum 2 layers** (application + database/security),
ensuring defense in depth against both accidental errors and intentional manipulation.
