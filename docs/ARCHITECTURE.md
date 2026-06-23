# NN Fund Management — Architecture

## Overview

Enterprise fund management system built on Odoo 18 Community Edition. Uses a ledger-based accounting architecture where all balances are derived from immutable posted ledger entries — never stored directly.

## Core Concepts

### Ledger-Based Double-Spending Prevention

All financial transactions post to `nn.fund.ledger` with strict debit/credit parity. Every entry has exactly one non-zero amount side (debit XOR credit). The `nn.fund.account._compute_balances` method aggregates all 14 transaction types to compute:

| Balance Field | Formula |
|---|---|
| `current_balance` | Sum of all debits - credits (14 types) |
| `held_balance` | Sum of hold entries only |
| `assigned_balance` | Sum of allocated/approved entries |
| `spent_balance` | Sum of spent entries (bills) |
| `transfer_out_balance` | Sum of transfer_approved_out |
| `available_balance` | `current - held - assigned - spent - transfer_out - requisition_approved` |

### 14 Transaction Types

```
incoming, allocation_hold, allocation_release, allocation_approve,
requisition_hold, requisition_release, requisition_approved,
bill_posted, bill_reversal,
transfer_hold, transfer_release, transfer_approved_out, transfer_approved_in,
adjustment
```

### Fund Flow

```
Incoming Fund (credit +balance)
  → Allocation Hold (debit available, add to held)
    → Allocation Release (remove held)
      → Allocation Approve (move from available to assigned)
  → Requisition Hold (debit available, add to held)
    → Requisition Release (remove held)
      → Requisition Approved (move from available to assigned)
        → Bill Posted (move from assigned to spent)
  → Transfer Hold (debit source available, add to held)
    → Transfer Release (remove held)
      → Transfer Approved Out (debit source balance)
      → Transfer Approved In (credit destination balance)
```

### Approval Engine

Three-tier approval system replaced by an **unlimited-level Dynamic Approval Matrix**:

- `nn.approval.matrix` — Configurable rules with amount ranges, project/expense head scoping, effective/expiration dates
- `nn.approval.matrix.line` — Individual approval steps within a matrix (sequence, group, user)
- **Adding a new approval level**: Create a new matrix line record — no Python code changes
- Matrix selection follows 4-tier fallback: exact project+head → project-only → head-only → global → old approval rule

### Workflow State Machine

Allocation: `draft → submitted → pending_approval → approved → cancelled/rejected`
Requisition: `draft → submitted → pending_approval → approved/closed → cancelled/rejected`
Transfer: `draft → submitted → pending_approval → approved → cancelled/rejected`
Incoming: `draft → confirmed → pending_verification → verified/reversed`
Bill: `draft → posted → cancelled`

### Multi-Company Isolation

Every financial model has a `company_id` field with `_check_company_auto = True`. Global record rules enforce strict company isolation via `[('company_id', '=', user.company_id.id)]`.

### Security Mixin

`nn.security.mixin` is inherited by all 10 financial models, providing:
- `_check_company_permission` — Server-side company isolation
- `_check_state_transition` — Validate state transitions
- `_check_duplicate_transaction` — Prevent double-posting
- `_validate_available_balance` — Uses `SELECT FOR UPDATE NOWAIT` for concurrent safety
- `_check_approval_sequence` — Ensures approval steps followed in order
- `_enforce_same_company` — Prevents cross-company operations

### Bank Email Integration

- `nn.bank.email.parser` — Per-bank regex configuration for extracting financial data from emails
- `nn.bank.email.log` — Processing log with dual deduplication (email_message_id + transaction_reference)
- Incoming funds from email start in `pending_verification` state, requiring explicit finance user verification

### Notification & Audit

- `mail.activity` for every workflow transition (todo assignments to approvers)
- `nn.approval.history` — Tracks all approval actions with matrix_line_id reference
- `nn.audit.log` — Tracks all financial actions (create, submit, approve, reject, cancel, transfer)
- `message_post` on all state transitions

## Key Files

| File | Purpose |
|---|---|
| `models/fund_account.py` | Account with computed balances (14 types) |
| `models/fund_ledger.py` | Immutable ledger entries |
| `models/incoming_fund.py` | Incoming fund with verification |
| `models/fund_allocation.py` | Allocation with dynamic approval |
| `models/fund_requisition.py` | Requisition with billable tracking |
| `models/fund_bill.py` | Bill against requisitions |
| `models/fund_transfer.py` | Cross-project transfers |
| `models/approval_matrix.py` | Dynamic approval matrix engine |
| `models/approval_history.py` | Approval audit log |
| `models/security_mixin.py` | 10-method security mixin |
| `models/bank_email_parser.py` | Email-to-fund parser |
| `models/dashboard.py` | Virtual dashboard models |
| `models/audit_log.py` | Financial audit trail |
| `controllers/main.py` | REST API + health endpoints |
| `api/main.py` | API key auth with rate limiting |
