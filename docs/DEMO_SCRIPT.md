# NN Fund Management — Interview Demo Script

## Overview

This 16-step demo walks through the complete fund lifecycle. Each step includes the UI path, the action to perform, and an **explanation script** — exact talking points to explain what's happening under the hood.

**Total time:** ~25 minutes

**Demo users** (created by demo data):

| User | Login | Password | Role |
|------|-------|----------|------|
| Alice Finance | alice | alice | Finance User |
| Bob GM | bob | bob | GM Approver |
| Carol MD | carol | carol | MD Approver |
| Dave Admin | dave | dave | Fund Administrator |

---

## Step 1: Receive 1,000,000 (2 min)

**UI Path:** `Fund Management > Incoming Funds`

**Action:** The demo data pre-creates an incoming fund of 1,000,000 with state "Confirmed". Open it to show the details.

**Explanation Script:**

> "Our demo starts with a 1,000,000 USD donation from the Demo Donor Foundation. This has already been confirmed — let me show you what happened.
>
> When we confirmed this incoming fund, the system created a single posted ledger entry of type `incoming` with a debit of 1,000,000 and credit of 0. This is the immutable record of the money arriving.
>
> Notice the Main Operating Account now shows:
> - **Current Balance:** 1,000,000
> - **Available Balance:** 1,000,000
>
> These are computed in real-time by aggregating all posted ledger entries. There are no stored balance fields that could get out of sync."

**Key points to demonstrate:**
- Click into the Fund Account to show the 5 computed balances
- Click "Ledger Entries" to show the single incoming entry
- Point out debit = 1,000,000, credit = 0.00, transaction_type = "incoming"

---

## Step 2: Allocate 600,000 (2 min)

**UI Path:** `Fund Management > Allocations > Create`

**Action:** Logged in as any user. Create a new Allocation:
- Fund Account: Main Operating Account
- Project: Project Alpha
- Amount: 600,000
- Purpose: "Core project funding for Q3 operations"
- Click **Save**, then **Submit**

**Explanation Script:**

> "We're allocating 600,000 to Project Alpha. When I click Submit, two things happen immediately:
>
> First, the system checks available balance — we have 1,000,000, so 600,000 is fine.
>
> Second, the system creates a **hold** ledger entry — a credit of 600,000 with transaction type `allocation_hold`. This reduces the available balance immediately, preventing any other transaction from spending this money while approval is pending.
>
> Now the allocation enters the approval workflow. Since 600,000 exceeds 200,000, it matches the **High Value** approval matrix, which requires 4 approvals in sequence: GM → Finance → MD → Board."

**Key points to demonstrate:**
- After submit, show state = "Pending Approval"
- Show the Current Step = "GM Approval"
- Go to the Fund Account — show available_balance dropped from 1,000,000 to 400,000 (1M - 600K hold)

---

## Step 3: Reject Allocation (1 min)

**UI Path:** Navigate to the allocation record

**Action:** Log in as **Bob GM** (bob/bob). Open the allocation. Click **Reject**. Enter comment: "Amount needs board pre-approval first."

**Explanation Script:**

> "Bob GM is the first approver in the matrix. He decides to reject. Notice the rejection:
>
> 1. Only current-step approvers (GM group) or administrators can reject — this is enforced server-side, not just in the UI
> 2. The system creates a **release** ledger entry — debit of 600,000 with type `allocation_release` — which reverses the hold
> 3. The allocation state becomes "Rejected"
> 4. The available balance returns to 1,000,000
>
> This is the **double-spending prevention** in action: the hold ensured that while rejection was pending, no other transaction could claim that 600,000. Now it's released back to the pool."

**Key points to demonstrate:**
- After reject, show state = "Rejected"
- Show the Fund Account — available_balance is back to 1,000,000
- Open Ledger Entries for the account — show the hold entry (credit 600K) and the release entry (debit 600K). They cancel out.

---

## Step 4: Reallocate 600,000 (1 min)

**UI Path:** Back to the rejected allocation. Click **Set to Draft**.

**Action:** Modify the purpose to "Revised proposal with board memo attached" and **Submit** again.

**Explanation Script:**

> "We can reset a rejected allocation back to draft, modify it, and resubmit. The same workflow re-runs:
> - Balance check
> - Hold entry created
> - Matrix re-evaluated (still High Value → 4-step approval)
> - First approver notified (GM)
>
> No data is lost — the approval history still shows the previous rejection. Full audit trail."

---

## Step 5: Approve Allocation — Multi-Step (4 min)

**UI Path:** Approve in sequence

**Action:** Four-step approval chain:
1. Log in as **Bob GM** (bob) → Approve
2. Log in as **Alice Finance** (alice) → Approve
3. Log in as **Carol MD** (carol) → Approve
4. Log in as **Dave Admin** (dave) → Approve

**After each step:** Show the allocation state stays "Pending Approval" but the Current Step advances.

**After final step:** Show state = "Approved".

**Explanation Script:**

> "This demonstrates the **Dynamic Approval Matrix** engine. Each time an approver approves, the system:
>
> 1. Verifies the user belongs to the correct group for the current step (server-side)
> 2. Advances `current_matrix_line_id` to the next step in sequence
> 3. Notifies the next group via `mail.activity`
>
> On the final approval, the system creates **three ledger entries** atomically:
> - `allocation_release` (debit 600K) — releases the hold
> - `allocation_approve` (credit 600K) — moves to assigned balance
>
> The available balance formula: `incoming + transfer_in - held - assigned - spent - transfer_out - requisition_approved`
>
> After approval: Available = 1,000,000 - 0 (held) - 600,000 (assigned) - 0 (spent) = **400,000**
>
> Approval history shows all 4 approvers with timestamps. Adding a 5th approval level requires only a new matrix line record — zero code changes."

**Key points to demonstrate:**
- Open Approval History — show 4 steps with different approvers
- Show Fund Account balances after final approval:
  - Held: 0 (release cleared it)
  - Assigned: 600,000
  - Available: 400,000
- Open Approval Matrices (`Configuration > Approval Matrices`) — show the High Value matrix with 4 lines

---

## Step 6: Transfer 200,000 A to B (2 min)

**UI Path:** `Fund Management > Transfers > Create`

**Action:** Create a Transfer:
- Source Project: Project Alpha
- Destination Project: Project Beta
- Amount: 200,000
- Reason: "Cross-project resource sharing"
- **Save → Submit**

**Explanation Script:**

> "We're transferring 200,000 from Project Alpha (Main Account) to Project Beta (Reserve Account). This is a cross-account transfer.
>
> On submit, the system:
> 1. Validates `source != destination` (server constraint)
> 2. Checks source available balance (400K — sufficient)
> 3. Creates a **hold** entry (credit 200K, type `transfer_hold`) on the source account
>
> Since 200K matches the High Value Transfer matrix, it needs GM → MD approval (2 steps)."

---

## Step 7: Approve Transfer (2 min)

**Action:**
1. Log in as **Bob GM** (bob) → Approve
2. Log in as **Carol MD** (carol) → Approve

**After final approval**, state becomes "Approved".

**Explanation Script:**

> "On final approval of a transfer, the system creates **three ledger entries** in a single transaction:
>
> 1. `transfer_release` (debit 200K on source) — releases the hold
> 2. `transfer_approved_out` (credit 200K on source) — reduces source balance
> 3. `transfer_approved_in` (debit 200K on destination) — increases destination balance
>
> Debits and credits are balanced across both accounts: total debits across both = total credits. The transfer is **atomic** — if any entry fails, all are rolled back.
>
> After transfer:
> - Main Account: Available = 400,000 - 0 (held) - 600K (assigned) - 200K (transfer_out) = **200,000**
> - Reserve Account: Available = 0 + 200K (transfer_in) = **200,000**
>
> The `transfer_approved_out` on source and `transfer_approved_in` on destination ensure both accounts reflect the movement immediately. No reconciliation step needed."

---

## Step 8: Create Requisition 150,000 (2 min)

**UI Path:** `Fund Management > Requisitions > Create`

**Action:** Create a Requisition:
- Project: Project Alpha
- Expense Head: Salaries (A-SAL)
- Amount: 150,000
- Notes: "Q3 salary disbursement"
- **Save → Submit**

**Explanation Script:**

> "A requisition reserves money for a specific purpose — in this case, salaries for Project Alpha.
>
> On submit, the ledger creates:
> - `requisition_hold` (credit 150K, type requisition_hold)
>
> After submit: Available on Main Account drops from 200K to **50K** (200K - 150K hold).
>
> Since 150K matches the Medium Value Requisition matrix, it needs 3-step approval: GM → Finance → MD."

**Key point to demonstrate:**
- Show Main Account available_balance: 50,000
- Show state = "Pending Approval" with Current Step "GM Approval"

---

## Step 9: Approve Requisition (2 min)

**Action:**
1. Log in as **Bob GM** (bob) → Approve
2. Log in as **Alice Finance** (alice) → Approve
3. Log in as **Carol MD** (carol) → Approve

**After final approval**, state becomes "Approved".

**Explanation Script:**

> "On final approval of a requisition, the system creates two ledger entries:
> - `requisition_release` (debit 150K) — releases the hold
> - `requisition_approved` (credit 150K) — moves to assigned/spending category
>
> After approval:
> - Available: 200,000 - 150K (requisition_approved) = **50,000**
>
> The requisition now has an `approved_amount` of 150,000 and a `remaining_billable_amount` of 150,000 — this is the amount available for bill posting."

---

## Step 10: Create Bill 100,000 (2 min)

**UI Path:** `Fund Management > Bills > Create`

**Action:** Create a Bill:
- Requisition: (select the one we just approved)
- Amount: 100,000
- Vendor: "ACME Consulting"
- Invoice Reference: "INV-2026-0421"
- **Save → Post**

**Explanation Script:**

> "We're posting a bill of 100,000 against the approved requisition.
>
> When I click Post, the system validates:
> 1. The requisition is in "approved" state
> 2. The bill amount (100K) does not exceed remaining_billable_amount (150K)
> 3. The bill's expense head matches the requisition's project — no cross-project billing
>
> Then it creates a `bill_posted` ledger entry (credit 100K, type `bill_posted`).
>
> After posting:
> - Remaining Billable on the requisition: 150K - 100K = **50,000**
> - Project Alpha spent amount: 100,000
> - Available balance on Main Account: Still 50,000 (the 150K was already set aside when the requisition was approved)"

---

## Step 11: Show Remaining Billable 50,000 (1 min)

**UI Path:** Open the Requisition record

**Action:** Point to the `remaining_billable_amount` field. It shows 50,000.

**Explanation Script:**

> "The `remaining_billable_amount` is a **computed, stored field** that tracks exactly how much more can be billed against this requisition without exceeding the approved amount.
>
> Formula: `approved_amount - sum(posted bill amounts) - released_amount`
>
> This field is updated in real-time as bills are posted or cancelled. It prevents overspending at the requisition level — an additional layer of control beyond the ledger balance checks.
>
> The `remaining_billable_amount` is computed via a stored `compute` method that triggers whenever:
> - A bill linked to this requisition is created or changes state
> - The requisition's own fields change
>
> This gives us instant, accurate spending tracking without manual reconciliation."

---

## Step 12: Attempt Bill 60,000 — Block (1 min)

**UI Path:** `Fund Management > Bills > Create`

**Action:** Create a new Bill:
- Requisition: (same one — remaining billable is 50K)
- Amount: 60,000
- **Save → Post**

**Explanation Script:**

> "Watch what happens when we try to bill 60,000 against a requisition that only has 50,000 remaining.
>
> The system raises a ValidationError: 'Bill amount (60,000) exceeds remaining billable amount (50,000) on requisition RQ/...'
>
> This is enforced at two levels:
> 1. The `_check_overbilling` SQL constraint on `nn.fund.bill` — server-side, cannot be bypassed via API
> 2. The `_validate_available_balance` call which checks the fund account's available balance
>
> This is **defense in depth** — even if a user somehow bypassed the UI validation, the server model validation catches it."

---

## Step 13: Attempt Cross-Project Billing — Block (1 min)

**UI Path:** `Fund Management > Bills > Create`

**Action:** Create a new Bill:
- Requisition: (same one — Project Alpha requisition)
- Expense Head: Switch to an expense head from **Project Beta** (e.g., "Materials" or "B-SAL")
- **Save → Post**

**Explanation Script:**

> "Here we try to bill against Project Alpha's requisition but use a Project Beta expense head. The system blocks this with:
>
> 'Bill expense head must match the requisition expense head.'
>
> This is enforced by the `_check_cross_validation` constraint on `nn.fund.bill` at lines 169-184. It validates:
> ```
> if req.project_id and bill.project_id:
>     if req.project_id.id != bill.project_id.id:
>         raise ValidationError("Cannot bill across different projects.")
> ```
>
> This prevents **cross-project fund leakage** — money allocated to Project A cannot be diverted to Project B expenses. Combined with multi-company isolation, this provides strong financial controls."

---

## Step 14: Close Requisition (1 min)

**UI Path:** Open the approved requisition

**Action:** Click **Close**.

**Explanation Script:**

> "Closing a requisition releases any remaining billable amount back to the available balance.
>
> Since we approved 150,000, billed 100,000, and the remaining_billable was 50,000, closing creates:
> - `requisition_release` ledger entry (debit 50K, type = requisition_release)
>
> This returns 50,000 to the available balance:
> - Available balance: 50,000 + 50,000 (released) = **100,000**
>
> The requisition state becomes 'Closed'. It can no longer have bills posted against it.
>
> This completes the full fund lifecycle: Receive → Allocate → Transfer → Requisition → Bill → Close."

---

## Step 15: Reconciliation Health Check (1 min)

**UI Path:** `Fund Management > Ledger Reconciliation`

**Action:** Click **Run Reconciliation** on a new reconciliation record.

**Explanation Script:**

> "The Ledger Reconciliation engine independently recomputes all balances from raw ledger aggregates — bypassing the stored computed fields entirely — and compares them against what the system reports.
>
> It checks:
> 1. **All 5 balance types** (current, held, assigned, available, spent) — stored vs derived
> 2. **Negative balances** — flagged as critical
> 3. **Duplicate entries** — same (reference, type, account, amount) composite key
> 4. **Missing entries** — approved records without expected ledger entries
> 5. **Orphan transactions** — ledger entries referencing deleted source records
>
> If any account has a critical issue (e.g., negative balance), `block_operations` is set to True and the security mixin's `_check_reconciliation_health()` prevents all financial operations until an administrator resolves and unblocks."

---

## Step 16: Live Architecture Walkthrough (3 min)

**UI Path:** Stay on the dashboard or any records view.

**Explanation Script:**

> "Let me summarize the key architectural decisions that make this system production-ready:
>
> **Ledger Architecture:** All 14 transaction types post to a single `nn.fund.ledger` table. Every entry has strict debit/credit parity. Balances are computed by `read_group` aggregation — never stored. This eliminates balance drift and reconciliation headaches.
>
> **Double-Spending Prevention:** Two mechanisms — (1) ledger holds reduce available balance on submission, (2) `SELECT FOR UPDATE NOWAIT` in `_validate_available_balance` locks the account row during balance checks, preventing concurrent transactions from consuming the same funds.
>
> **Dynamic Approval Matrix:** Unlimited levels configured via `nn.approval.matrix.line` records. Matrix selection uses 4-tier fallback: project+head → project-only → head-only → global. Adding a new approval level requires only a new record — no Python, no module upgrade.
>
> **Security Model:** Three layers — (1) Odoo record rules for multi-company isolation, (2) `nn.security.mixin` with 10 methods for server-side validation, (3) state machine rules enforced at model level. Every financial model inherits the mixin.
>
> **Reconciliation Engine:** Nightly cron runs 7 independent checks per account. `block_operations` flag prevents all financial activity on critical imbalance. The health check is called from `_validate_available_balance`, which is the gateway for all financial operations."

---

## Quick Reference: Balance Formula

```
available_balance =
    incoming (debits)
    + transfer_approved_in (debits)
    - allocation_hold (credits)
    - allocation_release (debits)  → reversed holds
    - allocation_approve (credits) → assigned
    - transfer_hold (credits)
    - transfer_release (debits)
    - transfer_approved_out (credits)
    - requisition_hold (credits)
    - requisition_release (debits)
    - requisition_approved (credits)
    - bill_posted (credits)
    + bill_reversal (debits)
```

All values ≥ 0 (floored at zero). All balances derived from `nn.fund.ledger` with `state = 'posted'`.

---

## Troubleshooting Demo Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Insufficient balance on submit | Previous step not completed | Check holds/releases from prior steps |
| "Not authorized" on approve | Logged in as wrong user | Switch to correct approver |
| Matrix not matching | Amount outside matrix range | Check min/max on demo matrices |
| Blocked operations | Reconciliation found critical issue | Run reconciliation and unblock |

---

## Demo Checklist

- [ ] Demo data loaded (`--i demo`)
- [ ] 4 user accounts available (alice, bob, carol, dave)
- [ ] Main Account shows 1,000,000 available
- [ ] All approval matrices visible in Configuration
- [ ] Projects and Expense Heads created
- [ ] Browser logged in as admin (or ready to switch users)
- [ ] Reconciliation ready to demonstrate
