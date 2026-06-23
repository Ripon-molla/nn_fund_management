"""NN Fund Management — Comprehensive Test Suite

This package contains all test files for the nn_fund_management Odoo module.
Tests are organized by feature area and tagged for targeted execution.

Run all tests:
    odoo-bin --test-enable --addons-path=... -d test_db --stop-after-init -i nn_fund_management

Run with coverage:
    odoo-bin --test-enable ... -- --cov=nn_fund_management

Test files:
    - test_fund_management.py      (Phase 4: 47 tests — allocation, requisition, bill, transfer, audit, ledger)
    - test_approval_matrix.py       (Phase 5.6a: 30 tests — matrix CRUD, scoping, workflow)
    - test_bank_email.py            (Phase 5.5: 25 tests — email parsing, processing, dedup)
    - test_ledger_reconciliation.py (Phase 5.6b: 27 tests — reconciliation engine)
    - test_security_mixin.py        (Phase 6: 24 tests — all 12 mixin methods + constraints)
    - test_incoming_fund.py         (Phase 6: 10 tests — reverse, closed account, constraints)
    - test_allocation_extended.py   (Phase 6: 8 tests — action_draft, onchanges, constraints)
    - test_concurrency.py           (Phase 6: 8 tests — race conditions, double-spending)
    - test_api_model.py             (Phase 6: 15 tests — API key, rate limiter, auth, audit log)
    - test_dashboard.py             (Phase 6: 7 tests — virtual dashboard models)
    - test_project_expense.py       (Phase 6: 9 tests — project & expense head models)
    - test_ledger_extended.py       (Phase 6: 9 tests — action_post, reverse, constraints)
    - test_bank_email_extended.py   (Phase 6: 8 tests — cron cleanup, view fund, reprocess)
    - test_approval_rule.py         (Phase 6: 5 tests — approval rule display, constraints, scoping)
    - test_full_workflow.py         (Phase 6: 7 tests — end-to-end lifecycle, multi-step, isolation)
    - test_reconciliation_extended.py (Phase 6: 11 tests — unique constraint, states, orphans, alerts)
    - test_financial_integrity.py    (Phase 6: 28 tests — ledger immutability, approval idempotency,
                                       transaction idempotency, concurrency, balance validation,
                                       reversal integrity, audit immutability, API replay protection,
                                       financial consistency, emergency recovery)
"""

from . import test_fund_management
from . import test_approval_matrix
from . import test_bank_email
from . import test_ledger_reconciliation
from . import test_security_mixin
from . import test_incoming_fund
from . import test_allocation_extended
from . import test_concurrency
from . import test_api_model
from . import test_dashboard
from . import test_project_expense
from . import test_ledger_extended
from . import test_bank_email_extended
from . import test_approval_rule
from . import test_full_workflow
from . import test_reconciliation_extended
from . import test_financial_integrity
