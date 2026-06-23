from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError
from odoo import fields


@tagged("fund_management", "allocation", "ledger", "security")
class TestFundAllocation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})

        company = cls.env.company

        cls.Account = cls.env["nn.fund.account"]
        cls.Allocation = cls.env["nn.fund.allocation"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ExpenseHead = cls.env["nn.expense.head"]
        cls.ApprovalHistory = cls.env["nn.approval.history"]
        cls.AuditLog = cls.env["nn.audit.log"]

        cls.fund_account = cls.Account.create(
            {
                "name": "Test Main Fund",
                "code": "TEST-MAIN",
                "type": "main",
                "company_id": company.id,
            }
        )

        cls.project = cls.Project.create(
            {
                "name": "Test Project",
                "code": "TEST-PRJ",
                "fund_account_id": cls.fund_account.id,
                "company_id": company.id,
            }
        )

        cls.expense_head = cls.ExpenseHead.create(
            {
                "name": "Test Expense Head",
                "code": "TEST-EH",
                "project_id": cls.project.id,
                "company_id": company.id,
            }
        )

        cls.GMGroup = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.MDGroup = cls.env.ref("nn_fund_management.group_md_approver")
        cls.AdminGroup = cls.env.ref("nn_fund_management.group_fund_administrator")

        cls.gm_user = cls._create_user("gm_approver", cls.GMGroup)
        cls.md_user = cls._create_user("md_approver", cls.MDGroup)
        cls.admin_user = cls._create_user("admin", cls.AdminGroup)

    @classmethod
    def _create_user(cls, login, group):
        user = cls.env["res.users"].create(
            {
                "name": login.title(),
                "login": login,
                "password": login,
                "groups_id": [(4, cls.env.ref("base.group_user").id), (4, group.id)],
            }
        )
        return user

    def _credit_fund_account(self, amount=100000.0):
        self.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "TEST-IN-001",
                "transaction_type": "incoming",
                "amount": amount,
                "fund_account_id": self.fund_account.id,
                "project_id": self.project.id,
                "reference_model": "nn.incoming.fund",
                "reference_id": 9999,
                "debit": amount,
                "credit": 0.0,
                "state": "posted",
                "company_id": self.env.company.id,
            }
        )

    def _create_allocation(self, amount=10000.0):
        return self.Allocation.create(
            {
                "fund_account_id": self.fund_account.id,
                "project_id": self.project.id,
                "amount": amount,
                "purpose": "Test allocation",
                "request_date": fields.Date.today(),
                "requested_by": self.env.user.id,
                "company_id": self.env.company.id,
            }
        )

    def test_allocation_create_with_request_number(self):
        alloc = self._create_allocation()
        self.assertTrue(alloc.request_number)
        self.assertNotEqual(alloc.request_number, "/")
        self.assertEqual(alloc.state, "draft")

    def test_project_expense_xor_both(self):
        with self.assertRaises(ValidationError):
            self.Allocation.create(
                {
                    "fund_account_id": self.fund_account.id,
                    "project_id": self.project.id,
                    "expense_head_id": self.expense_head.id,
                    "amount": 5000.0,
                    "purpose": "Both set",
                    "request_date": fields.Date.today(),
                    "requested_by": self.env.user.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_project_expense_xor_neither(self):
        with self.assertRaises(ValidationError):
            self.Allocation.create(
                {
                    "fund_account_id": self.fund_account.id,
                    "amount": 5000.0,
                    "purpose": "Neither set",
                    "request_date": fields.Date.today(),
                    "requested_by": self.env.user.id,
                    "company_id": self.env.company.id,
                }
            )

    def test_project_expense_xor_project_only(self):
        alloc = self._create_allocation()
        self.assertTrue(alloc.project_id)
        self.assertFalse(alloc.expense_head_id)

    def test_project_expense_xor_expense_only(self):
        alloc = self.Allocation.create(
            {
                "fund_account_id": self.fund_account.id,
                "expense_head_id": self.expense_head.id,
                "amount": 5000.0,
                "purpose": "Expense only",
                "request_date": fields.Date.today(),
                "requested_by": self.env.user.id,
                "company_id": self.env.company.id,
            }
        )
        self.assertTrue(alloc.expense_head_id)
        self.assertFalse(alloc.project_id)

    def test_allocation_hold(self):
        self._credit_fund_account()
        alloc = self._create_allocation(amount=50000.0)
        balance_before = self.fund_account.available_balance
        alloc.action_submit()
        self.assertIn(alloc.state, ("submitted", "pending_approval"))
        hold_ledger = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_hold"),
            ]
        )
        self.assertTrue(hold_ledger)
        self.assertEqual(hold_ledger[0].credit, 50000.0)
        self.assertEqual(hold_ledger[0].state, "posted")
        self.fund_account.invalidate_recordset()
        expected_available = balance_before - 50000.0
        self.assertEqual(
            self.fund_account.available_balance,
            expected_available,
            "Held funds must not be available for other allocations",
        )

    def test_allocation_reject_releases_hold(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=30000.0)
        alloc.action_submit()
        balance_after_hold = self.fund_account.available_balance
        alloc.action_reject()
        self.assertEqual(alloc.state, "rejected")
        release_ledger = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_release"),
            ]
        )
        self.assertTrue(release_ledger)
        self.assertEqual(release_ledger[0].debit, 30000.0)
        self.fund_account.invalidate_recordset()
        self.assertEqual(
            self.fund_account.available_balance,
            balance_after_hold + 30000.0,
            "Funds must be returned to available balance on reject",
        )

    def test_allocation_full_approval(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=20000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            alloc.with_user(self.gm_user).action_approve()
        self.assertEqual(alloc.state, "approved")
        release_ledger = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_release"),
            ]
        )
        self.assertTrue(release_ledger, "Release entry must exist for approved allocation")
        approve_ledger = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_approve"),
            ]
        )
        self.assertTrue(approve_ledger, "Approve ledger entry must exist")
        self.assertEqual(approve_ledger[0].credit, 20000.0)

    def test_insufficient_balance(self):
        self._credit_fund_account(amount=10000.0)
        alloc = self._create_allocation(amount=50000.0)
        with self.assertRaises(ValidationError):
            alloc.action_submit()

    def test_duplicate_approval_prevention(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=15000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            alloc.with_user(self.gm_user).action_approve()
        if alloc.state == "pending_approval":
            alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")
        with self.assertRaises(ValidationError):
            alloc.action_approve()

    def test_gm_permission(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=25000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            with self.assertRaises(ValidationError):
                alloc.with_user(self.env.user).action_approve()

    def test_md_permission(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=25000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            alloc.with_user(self.gm_user).action_approve()
        if alloc.state == "pending_approval":
            with self.assertRaises(ValidationError):
                alloc.with_user(self.gm_user).action_approve()

    def test_submit_from_non_draft(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=10000.0)
        alloc.action_submit()
        with self.assertRaises(ValidationError):
            alloc.action_submit()

    def test_reject_from_approved(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=10000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            alloc.with_user(self.gm_user).action_approve()
        if alloc.state == "pending_approval":
            alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")
        with self.assertRaises(ValidationError):
            alloc.action_reject()

    def test_cancel_releases_hold(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=15000.0)
        alloc.action_submit()
        balance_after_hold = self.fund_account.available_balance
        alloc.action_cancel()
        self.assertEqual(alloc.state, "cancelled")
        self.fund_account.invalidate_recordset()
        self.assertGreater(
            self.fund_account.available_balance,
            balance_after_hold,
        )

    def test_ledger_immutability_posted(self):
        self._credit_fund_account(amount=50000.0)
        alloc = self._create_allocation(amount=5000.0)
        alloc.action_submit()
        hold_entry = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_hold"),
            ],
            limit=1,
        )
        with self.assertRaises(UserError):
            hold_entry.write({"note": "Attempt to modify"})

    def test_ledger_immutability_delete(self):
        self._credit_fund_account(amount=50000.0)
        alloc = self._create_allocation(amount=5000.0)
        alloc.action_submit()
        hold_entry = self.Ledger.search(
            [
                ("reference_model", "=", "nn.fund.allocation"),
                ("reference_id", "=", alloc.id),
                ("transaction_type", "=", "allocation_hold"),
            ],
            limit=1,
        )
        with self.assertRaises(UserError):
            hold_entry.unlink()

    def test_multi_step_approval_workflow(self):
        self._credit_fund_account(amount=200000.0)
        alloc = self._create_allocation(amount=100000.0)
        alloc.action_submit()
        if alloc.state == "pending_approval":
            alloc.with_user(self.gm_user).action_approve()
        if alloc.state == "pending_approval":
            alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    def test_approval_history_recorded(self):
        self._credit_fund_account(amount=100000.0)
        alloc = self._create_allocation(amount=10000.0)
        alloc.action_submit()
        history = self.ApprovalHistory.search(
            [
                ("request_type", "=", "nn.fund.allocation"),
                ("request_id", "=", alloc.id),
            ]
        )
        self.assertTrue(history)
        self.assertIn("submitted", history.mapped("new_state"))


@tagged("fund_management", "ledger")
class TestFundLedger(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        cls.Account = cls.env["nn.fund.account"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.fund_account = cls.Account.create(
            {
                "name": "Ledger Test Account",
                "code": "LEDGER-TEST",
                "type": "main",
                "company_id": cls.env.company.id,
            }
        )
        cls.project = cls.Project.create(
            {
                "name": "Ledger Test Project",
                "code": "LEDGER-PRJ",
                "fund_account_id": cls.fund_account.id,
                "company_id": cls.env.company.id,
            }
        )

    def _create_entry(self, transaction_type, debit=0.0, credit=0.0):
        return self.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "ENTRY-%d" % self.Ledger.search_count([]),
                "transaction_type": transaction_type,
                "fund_account_id": self.fund_account.id,
                "project_id": self.project.id,
                "reference_model": "test.model",
                "reference_id": 1,
                "debit": debit,
                "credit": credit,
                "state": "posted",
                "company_id": self.env.company.id,
            }
        )

    def test_debit_credit_constraint_both_positive(self):
        with self.assertRaises(ValidationError):
            self._create_entry("incoming", debit=100.0, credit=50.0)

    def test_debit_credit_constraint_both_zero(self):
        with self.assertRaises(ValidationError):
            self._create_entry("incoming", debit=0.0, credit=0.0)

    def test_ledger_reversal(self):
        entry = self._create_entry("incoming", debit=10000.0, credit=0.0)
        self.assertEqual(entry.state, "posted")
        reverse = entry.action_reverse()
        self.assertTrue(reverse)
        self.assertEqual(entry.state, "reversed")
        self.assertEqual(reverse.debit, 0.0)
        self.assertEqual(reverse.credit, 10000.0)

    def test_amount_computed(self):
        entry = self._create_entry("incoming", debit=5000.0, credit=0.0)
        self.assertEqual(entry.amount, 5000.0)
        entry2 = self._create_entry("allocation_hold", debit=0.0, credit=3000.0)
        self.assertEqual(entry2.amount, 3000.0)


@tagged("fund_management", "account")
class TestFundAccount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        cls.Account = cls.env["nn.fund.account"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.account = cls.Account.create(
            {
                "name": "Balance Test Account",
                "code": "BAL-TEST",
                "type": "main",
                "company_id": cls.env.company.id,
            }
        )

    def _post_entry(self, ttype, debit=0.0, credit=0.0):
        self.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "BAL-ENTRY-%d" % self.Ledger.search_count([]),
                "transaction_type": ttype,
                "fund_account_id": self.account.id,
                "reference_model": "test.model",
                "reference_id": 1,
                "debit": debit,
                "credit": credit,
                "state": "posted",
                "company_id": self.env.company.id,
            }
        )
        self.account.invalidate_recordset()

    def test_incoming_increases_balance(self):
        self._post_entry("incoming", debit=50000.0, credit=0.0)
        self.assertEqual(self.account.current_balance, 50000.0)

    def test_hold_reduces_available(self):
        self._post_entry("incoming", debit=100000.0, credit=0.0)
        self._post_entry("allocation_hold", debit=0.0, credit=30000.0)
        self.assertEqual(self.account.current_balance, 70000.0)
        self.assertEqual(self.account.held_balance, 30000.0)

    def test_release_restores_balance(self):
        self._post_entry("incoming", debit=100000.0, credit=0.0)
        self._post_entry("allocation_hold", debit=0.0, credit=30000.0)
        self._post_entry("allocation_release", debit=30000.0, credit=0.0)
        self.assertEqual(self.account.current_balance, 100000.0)
        self.assertEqual(self.account.held_balance, 0.0)

    def test_approve_reduces_available(self):
        self._post_entry("incoming", debit=100000.0, credit=0.0)
        self._post_entry("allocation_hold", debit=0.0, credit=30000.0)
        self._post_entry("allocation_release", debit=30000.0, credit=0.0)
        self._post_entry("allocation_approve", debit=0.0, credit=30000.0)
        self.assertEqual(self.account.current_balance, 70000.0)
        self.assertEqual(self.account.assigned_balance, 30000.0)

    def test_available_balance_formula(self):
        self._post_entry("incoming", debit=200000.0, credit=0.0)
        self._post_entry("allocation_hold", debit=0.0, credit=50000.0)
        self._post_entry("allocation_release", debit=50000.0, credit=0.0)
        self._post_entry("allocation_approve", debit=0.0, credit=50000.0)
        self._post_entry("bill_posted", debit=0.0, credit=20000.0)
        self.assertEqual(self.account.available_balance, 130000.0)


@tagged("fund_management", "audit")
class TestAuditTrail(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        cls.Account = cls.env["nn.fund.account"]
        cls.Allocation = cls.env["nn.fund.allocation"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ApprovalHistory = cls.env["nn.approval.history"]
        cls.AuditLog = cls.env["nn.audit.log"]
        cls.fund_account = cls.Account.create(
            {
                "name": "Audit Test Account",
                "code": "AUDIT-TEST",
                "type": "main",
                "company_id": cls.env.company.id,
            }
        )
        cls.project = cls.Project.create(
            {
                "name": "Audit Test Project",
                "code": "AUDIT-PRJ",
                "fund_account_id": cls.fund_account.id,
                "company_id": cls.env.company.id,
            }
        )

    def _credit(self, amount=100000.0):
        self.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "AUDIT-IN",
                "transaction_type": "incoming",
                "amount": amount,
                "fund_account_id": self.fund_account.id,
                "reference_model": "nn.incoming.fund",
                "reference_id": 1,
                "debit": amount,
                "credit": 0.0,
                "state": "posted",
                "company_id": self.env.company.id,
            }
        )

    def test_audit_log_on_create(self):
        self._credit()
        alloc = self.Allocation.create(
            {
                "fund_account_id": self.fund_account.id,
                "project_id": self.project.id,
                "amount": 5000.0,
                "purpose": "Audit test",
                "request_date": fields.Date.today(),
                "requested_by": self.env.user.id,
                "company_id": self.env.company.id,
            }
        )
        audit_logs = self.AuditLog.search(
            [
                ("model", "=", "nn.fund.allocation"),
                ("res_id", "=", alloc.id),
            ]
        )
        self.assertTrue(audit_logs)

    def test_allocation_creates_approval_history(self):
        self._credit()
        alloc = self.Allocation.create(
            {
                "fund_account_id": self.fund_account.id,
                "project_id": self.project.id,
                "amount": 5000.0,
                "purpose": "History test",
                "request_date": fields.Date.today(),
                "requested_by": self.env.user.id,
                "company_id": self.env.company.id,
            }
        )
        alloc.action_submit()
        history = self.ApprovalHistory.search(
            [
                ("request_type", "=", "nn.fund.allocation"),
                ("request_id", "=", alloc.id),
            ]
        )
        self.assertTrue(history)


@tagged("fund_management", "requisition")
class TestRequisition(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        company = cls.env.company

        cls.Account = cls.env["nn.fund.account"]
        cls.Requisition = cls.env["nn.fund.requisition"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ExpenseHead = cls.env["nn.expense.head"]
        cls.Bill = cls.env["nn.fund.bill"]
        cls.ApprovalHistory = cls.env["nn.approval.history"]

        cls.GMGroup = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.MDGroup = cls.env.ref("nn_fund_management.group_md_approver")

        cls.gm_user = cls._create_user("req_gm", cls.GMGroup)
        cls.md_user = cls._create_user("req_md", cls.MDGroup)

        cls.fund_account = cls.Account.create(
            {
                "name": "Requisition Test Fund",
                "code": "REQ-TEST",
                "type": "main",
                "company_id": company.id,
            }
        )

        cls.project = cls.Project.create(
            {
                "name": "Requisition Test Project",
                "code": "REQ-PRJ",
                "fund_account_id": cls.fund_account.id,
                "company_id": company.id,
            }
        )

        cls.expense_head = cls.ExpenseHead.create(
            {
                "name": "Requisition Test EH",
                "code": "REQ-EH",
                "project_id": cls.project.id,
                "company_id": company.id,
            }
        )

        cls.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "REQ-FUND-IN",
                "transaction_type": "incoming",
                "fund_account_id": cls.fund_account.id,
                "project_id": cls.project.id,
                "reference_model": "nn.incoming.fund",
                "reference_id": 9999,
                "debit": 200000.0,
                "credit": 0.0,
                "state": "posted",
                "company_id": company.id,
            }
        )

    @classmethod
    def _create_user(cls, login, group):
        return cls.env["res.users"].create(
            {
                "name": login.title(),
                "login": login,
                "password": login,
                "groups_id": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, group.id),
                ],
            }
        )

    def _create_requisition(self, amount=10000.0, use_project=True):
        vals = {
            "amount": amount,
            "company_id": self.env.company.id,
        }
        if use_project:
            vals["project_id"] = self.project.id
        else:
            vals["expense_head_id"] = self.expense_head.id
        return self.Requisition.create(vals)

    def _approve_fully(self, req):
        req.action_submit()
        if req.state == "pending_approval":
            req.with_user(self.gm_user).action_approve()
        if req.state == "pending_approval":
            req.with_user(self.md_user).action_approve()
        return req

    def test_requisition_create(self):
        req = self._create_requisition()
        self.assertTrue(req.reference)
        self.assertEqual(req.state, "draft")
        self.assertEqual(req.amount, 10000.0)
        self.assertEqual(req.project_id, self.project)
        self.assertFalse(req.expense_head_id)

    def test_requisition_xor_project_only(self):
        req = self._create_requisition(use_project=True)
        self.assertTrue(req.project_id)
        self.assertFalse(req.expense_head_id)

    def test_requisition_xor_expense_only(self):
        req = self._create_requisition(use_project=False)
        self.assertTrue(req.expense_head_id)
        self.assertFalse(req.project_id)

    def test_requisition_xor_neither(self):
        with self.assertRaises(ValidationError):
            self.Requisition.create({
                "amount": 5000.0,
                "company_id": self.env.company.id,
            })

    def test_requisition_xor_both_mismatch(self):
        other_project = self.Project.create({
            "name": "Other Project",
            "code": "OTHER",
            "fund_account_id": self.fund_account.id,
            "company_id": self.env.company.id,
        })
        other_eh = self.ExpenseHead.create({
            "name": "Other EH",
            "code": "OTH-EH",
            "project_id": other_project.id,
            "company_id": self.env.company.id,
        })
        with self.assertRaises(ValidationError):
            self.Requisition.create({
                "project_id": self.project.id,
                "expense_head_id": other_eh.id,
                "amount": 5000.0,
                "company_id": self.env.company.id,
            })

    def test_requisition_hold_on_submit(self):
        req = self._create_requisition(amount=50000.0)
        req.action_submit()
        self.assertIn(req.state, ("submitted", "pending_approval"))
        hold = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_hold"),
        ])
        self.assertTrue(hold)
        self.assertEqual(hold[0].credit, 50000.0)

    def test_requisition_release_release_on_reject(self):
        req = self._create_requisition(amount=30000.0)
        req.action_submit()
        hold_entries = self.Ledger.search_count([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_hold"),
        ])
        self.assertEqual(hold_entries, 1)
        if req.state in ("submitted", "pending_approval"):
            req.action_reject()
        self.assertEqual(req.state, "rejected")
        release = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_release"),
        ])
        self.assertTrue(release)
        self.assertEqual(release[0].debit, 30000.0)

    def test_requisition_full_approval(self):
        req = self._create_requisition(amount=20000.0)
        self._approve_fully(req)
        self.assertEqual(req.state, "approved")
        self.assertEqual(req.approved_amount, 20000.0)
        release = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_release"),
        ])
        self.assertTrue(release)
        approved_ledger = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_approved"),
        ])
        self.assertTrue(approved_ledger)
        self.assertEqual(approved_ledger[0].credit, 20000.0)

    def test_requisition_remaining_billable(self):
        req = self._create_requisition(amount=50000.0)
        self._approve_fully(req)
        self.assertEqual(req.remaining_billable_amount, 50000.0)
        self.assertEqual(req.billed_amount, 0.0)

    def test_requisition_close_releases_remaining(self):
        req = self._create_requisition(amount=50000.0)
        self._approve_fully(req)
        req.action_close()
        self.assertEqual(req.state, "closed")
        self.assertEqual(req.remaining_billable_amount, 0.0)
        self.assertEqual(req.released_amount, 50000.0)
        release_close = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_release"),
            ("reference", "=", req.reference + "-REL-CLOSE"),
        ])
        self.assertTrue(release_close)
        self.assertEqual(release_close[0].debit, 50000.0)

    def test_requisition_fund_account_computed(self):
        req = self._create_requisition(use_project=True)
        self.assertEqual(req.fund_account_id, self.fund_account)
        req2 = self._create_requisition(use_project=False)
        self.assertEqual(req2.fund_account_id, self.fund_account)

    def test_requisition_cancel_releases_hold(self):
        req = self._create_requisition(amount=25000.0)
        req.action_submit()
        req.action_cancel()
        self.assertEqual(req.state, "cancelled")
        release = self.Ledger.search([
            ("reference_model", "=", "nn.fund.requisition"),
            ("reference_id", "=", req.id),
            ("transaction_type", "=", "requisition_release"),
        ])
        self.assertTrue(release)

    def test_requisition_approval_history(self):
        req = self._create_requisition(amount=10000.0)
        req.action_submit()
        history = self.ApprovalHistory.search([
            ("request_type", "=", "nn.fund.requisition"),
            ("request_id", "=", req.id),
        ])
        self.assertTrue(history)


@tagged("fund_management", "bill")
class TestBill(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        company = cls.env.company

        cls.Account = cls.env["nn.fund.account"]
        cls.Requisition = cls.env["nn.fund.requisition"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ExpenseHead = cls.env["nn.expense.head"]
        cls.Bill = cls.env["nn.fund.bill"]

        cls.GMGroup = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.MDGroup = cls.env.ref("nn_fund_management.group_md_approver")

        cls.gm_user = cls._create_user("bill_gm", cls.GMGroup)
        cls.md_user = cls._create_user("bill_md", cls.MDGroup)

        cls.fund_account = cls.Account.create(
            {
                "name": "Bill Test Fund",
                "code": "BILL-TEST",
                "type": "main",
                "company_id": company.id,
            }
        )

        cls.project = cls.Project.create(
            {
                "name": "Bill Test Project",
                "code": "BILL-PRJ",
                "fund_account_id": cls.fund_account.id,
                "company_id": company.id,
            }
        )

        cls.expense_head = cls.ExpenseHead.create(
            {
                "name": "Bill Test EH",
                "code": "BILL-EH",
                "project_id": cls.project.id,
                "company_id": company.id,
            }
        )

        cls.Ledger.create(
            {
                "date": fields.Datetime.now(),
                "reference": "BILL-FUND-IN",
                "transaction_type": "incoming",
                "fund_account_id": cls.fund_account.id,
                "project_id": cls.project.id,
                "reference_model": "nn.incoming.fund",
                "reference_id": 9999,
                "debit": 200000.0,
                "credit": 0.0,
                "state": "posted",
                "company_id": company.id,
            }
        )

        cls.requisition = cls.Requisition.create({
            "project_id": cls.project.id,
            "amount": 100000.0,
            "company_id": company.id,
        })
        cls.requisition.action_submit()
        if cls.requisition.state == "pending_approval":
            cls.requisition.with_user(cls.gm_user).action_approve()
        if cls.requisition.state == "pending_approval":
            cls.requisition.with_user(cls.md_user).action_approve()
        cls.requisition.invalidate_recordset()

    @classmethod
    def _create_user(cls, login, group):
        return cls.env["res.users"].create(
            {
                "name": login.title(),
                "login": login,
                "password": login,
                "groups_id": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, group.id),
                ],
            }
        )

    def _create_bill(self, amount=10000.0):
        return self.Bill.create({
            "requisition_id": self.requisition.id,
            "expense_head_id": self.expense_head.id,
            "amount": amount,
            "company_id": self.env.company.id,
        })

    def test_bill_create(self):
        bill = self._create_bill()
        self.assertTrue(bill.reference)
        self.assertEqual(bill.state, "draft")
        self.assertEqual(bill.project_id, self.project)
        self.assertEqual(bill.fund_account_id, self.fund_account)

    def test_bill_post(self):
        bill = self._create_bill(amount=25000.0)
        bill.action_post()
        self.assertEqual(bill.state, "posted")
        self.assertTrue(bill.ledger_entry_id)
        self.assertEqual(bill.ledger_entry_id.transaction_type, "bill_posted")
        self.assertEqual(bill.ledger_entry_id.credit, 25000.0)

    def test_bill_partial_billing(self):
        bill1 = self._create_bill(amount=30000.0)
        bill1.action_post()
        self.requisition.invalidate_recordset()
        self.assertEqual(self.requisition.remaining_billable_amount, 70000.0)
        self.assertEqual(self.requisition.billed_amount, 30000.0)
        bill2 = self._create_bill(amount=40000.0)
        bill2.action_post()
        self.requisition.invalidate_recordset()
        self.assertEqual(self.requisition.remaining_billable_amount, 30000.0)
        self.assertEqual(self.requisition.billed_amount, 70000.0)

    def test_bill_overbilling_prevention(self):
        with self.assertRaises(ValidationError):
            bill = self._create_bill(amount=200000.0)
            bill.action_post()

    def test_bill_cancel(self):
        bill = self._create_bill(amount=15000.0)
        bill.action_post()
        self.requisition.invalidate_recordset()
        remaining_before = self.requisition.remaining_billable_amount
        bill.action_cancel()
        self.assertEqual(bill.state, "cancelled")
        self.assertTrue(bill.cancellation_ledger_entry_id)
        self.assertEqual(
            bill.cancellation_ledger_entry_id.transaction_type, "bill_reversal"
        )
        self.assertEqual(bill.cancellation_ledger_entry_id.debit, 15000.0)
        self.requisition.invalidate_recordset()
        self.assertEqual(
            self.requisition.remaining_billable_amount,
            remaining_before + 15000.0,
        )

    def test_bill_project_isolation(self):
        other_project = self.Project.create({
            "name": "Other Bill Project",
            "code": "BILL-OTH",
            "fund_account_id": self.fund_account.id,
            "company_id": self.env.company.id,
        })
        other_eh = self.ExpenseHead.create({
            "name": "Other Bill EH",
            "code": "BILL-OE",
            "project_id": other_project.id,
            "company_id": self.env.company.id,
        })
        with self.assertRaises(ValidationError):
            self.Bill.create({
                "requisition_id": self.requisition.id,
                "expense_head_id": other_eh.id,
                "amount": 5000.0,
                "company_id": self.env.company.id,
            })

    def test_bill_ledger_entries(self):
        bill = self._create_bill(amount=20000.0)
        bill.action_post()
        all_entries = bill.ledger_entry_ids
        self.assertTrue(all_entries)
        self.assertIn(bill.ledger_entry_id, all_entries)

    def test_bill_close_requisition_with_bills(self):
        bill = self._create_bill(amount=40000.0)
        bill.action_post()
        self.requisition.invalidate_recordset()
        self.requisition.action_close()
        self.assertEqual(self.requisition.state, "closed")
        self.assertEqual(
            self.requisition.released_amount,
            60000.0,
        )
        self.assertEqual(
            self.requisition.remaining_billable_amount,
            0.0,
        )


@tagged("fund_management", "transfer")
class TestTransfer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        company = cls.env.company

        cls.Account = cls.env["nn.fund.account"]
        cls.Transfer = cls.env["nn.fund.transfer"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ExpenseHead = cls.env["nn.expense.head"]
        cls.AuditLog = cls.env["nn.audit.log"]
        cls.ApprovalHistory = cls.env["nn.approval.history"]

        cls.GMGroup = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.MDGroup = cls.env.ref("nn_fund_management.group_md_approver")

        cls.gm_user = cls._create_user("transfer_gm", cls.GMGroup)
        cls.md_user = cls._create_user("transfer_md", cls.MDGroup)

        cls.src_account = cls.Account.create({
            "name": "Source Transfer Account",
            "code": "SRC-TRF",
            "type": "main",
            "company_id": company.id,
        })
        cls.dst_account = cls.Account.create({
            "name": "Dest Transfer Account",
            "code": "DST-TRF",
            "type": "main",
            "company_id": company.id,
        })

        cls.src_project = cls.Project.create({
            "name": "Source Transfer Project",
            "code": "SRC-PRJ",
            "fund_account_id": cls.src_account.id,
            "company_id": company.id,
        })
        cls.dst_project = cls.Project.create({
            "name": "Dest Transfer Project",
            "code": "DST-PRJ",
            "fund_account_id": cls.dst_account.id,
            "company_id": company.id,
        })

        cls.src_eh = cls.ExpenseHead.create({
            "name": "Source Transfer EH",
            "code": "SRC-EH",
            "project_id": cls.src_project.id,
            "company_id": company.id,
        })
        cls.dst_eh = cls.ExpenseHead.create({
            "name": "Dest Transfer EH",
            "code": "DST-EH",
            "project_id": cls.dst_project.id,
            "company_id": company.id,
        })

        cls.Ledger.create({
            "date": fields.Datetime.now(),
            "reference": "TRF-FUND-SRC",
            "transaction_type": "incoming",
            "fund_account_id": cls.src_account.id,
            "project_id": cls.src_project.id,
            "reference_model": "nn.incoming.fund",
            "reference_id": 9999,
            "debit": 200000.0,
            "credit": 0.0,
            "state": "posted",
            "company_id": company.id,
        })
        cls.Ledger.create({
            "date": fields.Datetime.now(),
            "reference": "TRF-FUND-DST",
            "transaction_type": "incoming",
            "fund_account_id": cls.dst_account.id,
            "project_id": cls.dst_project.id,
            "reference_model": "nn.incoming.fund",
            "reference_id": 9998,
            "debit": 100000.0,
            "credit": 0.0,
            "state": "posted",
            "company_id": company.id,
        })

    @classmethod
    def _create_user(cls, login, group):
        return cls.env["res.users"].create({
            "name": login.title(),
            "login": login,
            "password": login,
            "groups_id": [
                (4, cls.env.ref("base.group_user").id),
                (4, group.id),
            ],
        })

    def _create_transfer(self, amount=50000.0):
        return self.Transfer.create({
            "source_project_id": self.src_project.id,
            "destination_project_id": self.dst_project.id,
            "amount": amount,
            "reason": "Test transfer",
            "company_id": self.env.company.id,
        })

    def _approve_fully(self, transfer):
        transfer.action_submit()
        if transfer.state == "pending_approval":
            transfer.with_user(self.gm_user).action_approve()
        if transfer.state == "pending_approval":
            transfer.with_user(self.md_user).action_approve()
        return transfer

    def test_transfer_create(self):
        trf = self._create_transfer()
        self.assertTrue(trf.reference)
        self.assertEqual(trf.state, "draft")
        self.assertEqual(trf.amount, 50000.0)
        self.assertEqual(trf.source_project_id, self.src_project)
        self.assertEqual(trf.destination_project_id, self.dst_project)

    def test_transfer_xor_source_project(self):
        trf = self.Transfer.create({
            "source_expense_head_id": self.src_eh.id,
            "destination_project_id": self.dst_project.id,
            "amount": 10000.0,
            "company_id": self.env.company.id,
        })
        self.assertTrue(trf.source_expense_head_id)
        self.assertFalse(trf.source_project_id)
        self.assertEqual(trf.source_fund_account_id, self.src_account)

    def test_transfer_xor_dest_expense(self):
        trf = self.Transfer.create({
            "source_project_id": self.src_project.id,
            "destination_expense_head_id": self.dst_eh.id,
            "amount": 10000.0,
            "company_id": self.env.company.id,
        })
        self.assertTrue(trf.destination_expense_head_id)
        self.assertFalse(trf.destination_project_id)
        self.assertEqual(trf.destination_fund_account_id, self.dst_account)

    def test_transfer_same_source_destination(self):
        with self.assertRaises(ValidationError):
            self.Transfer.create({
                "source_project_id": self.src_project.id,
                "destination_project_id": self.src_project.id,
                "amount": 10000.0,
                "company_id": self.env.company.id,
            })

    def test_transfer_same_expense_head(self):
        with self.assertRaises(ValidationError):
            self.Transfer.create({
                "source_expense_head_id": self.src_eh.id,
                "destination_expense_head_id": self.src_eh.id,
                "amount": 10000.0,
                "company_id": self.env.company.id,
            })

    def test_transfer_insufficient_balance(self):
        trf = self.Transfer.create({
            "source_project_id": self.src_project.id,
            "destination_project_id": self.dst_project.id,
            "amount": 500000.0,
            "company_id": self.env.company.id,
        })
        with self.assertRaises(ValidationError):
            trf.action_submit()

    def test_transfer_hold_on_submit(self):
        trf = self._create_transfer(amount=30000.0)
        trf.action_submit()
        self.assertIn(trf.state, ("submitted", "pending_approval"))
        hold = self.Ledger.search([
            ("reference_model", "=", "nn.fund.transfer"),
            ("reference_id", "=", trf.id),
            ("transaction_type", "=", "transfer_hold"),
        ])
        self.assertTrue(hold)
        self.assertEqual(hold[0].credit, 30000.0)
        self.assertEqual(hold[0].fund_account_id, self.src_account)

    def test_transfer_reject_releases(self):
        trf = self._create_transfer(amount=25000.0)
        trf.action_submit()
        trf.action_reject()
        self.assertEqual(trf.state, "rejected")
        release = self.Ledger.search([
            ("reference_model", "=", "nn.fund.transfer"),
            ("reference_id", "=", trf.id),
            ("transaction_type", "=", "transfer_release"),
        ])
        self.assertTrue(release)
        self.assertEqual(release[0].debit, 25000.0)

    def test_transfer_cancel_releases(self):
        trf = self._create_transfer(amount=20000.0)
        trf.action_submit()
        trf.action_cancel()
        self.assertEqual(trf.state, "cancelled")
        release = self.Ledger.search([
            ("reference_model", "=", "nn.fund.transfer"),
            ("reference_id", "=", trf.id),
            ("transaction_type", "=", "transfer_release"),
        ])
        self.assertTrue(release)

    def test_transfer_full_approval(self):
        trf = self._create_transfer(amount=40000.0)
        self._approve_fully(trf)
        self.assertEqual(trf.state, "approved")
        self.assertTrue(trf.source_ledger_entry_id)
        self.assertTrue(trf.destination_ledger_entry_id)
        self.assertEqual(
            trf.source_ledger_entry_id.transaction_type,
            "transfer_approved_out",
        )
        self.assertEqual(
            trf.destination_ledger_entry_id.transaction_type,
            "transfer_approved_in",
        )
        self.assertEqual(trf.source_ledger_entry_id.credit, 40000.0)
        self.assertEqual(trf.destination_ledger_entry_id.debit, 40000.0)

    def test_transfer_cross_project_balance(self):
        src_before = self.src_account.current_balance
        dst_before = self.dst_account.current_balance
        trf = self._create_transfer(amount=50000.0)
        self._approve_fully(trf)
        self.src_account.invalidate_recordset()
        self.dst_account.invalidate_recordset()
        self.assertEqual(
            self.src_account.current_balance,
            src_before - 50000.0,
        )
        self.assertEqual(
            self.dst_account.current_balance,
            dst_before + 50000.0,
        )

    def test_transfer_audit_log_creation(self):
        trf = self._create_transfer(amount=15000.0)
        logs = self.AuditLog.search([
            ("model", "=", "nn.fund.transfer"),
            ("res_id", "=", trf.id),
        ])
        self.assertTrue(logs, "Audit log should be created on transfer create")

    def test_transfer_audit_log_on_approve(self):
        trf = self._create_transfer(amount=35000.0)
        self._approve_fully(trf)
        transfer_logs = self.AuditLog.search([
            ("model", "=", "nn.fund.transfer"),
            ("res_id", "=", trf.id),
            ("action", "=", "transfer"),
        ])
        self.assertTrue(transfer_logs)

    def test_transfer_approval_history(self):
        trf = self._create_transfer(amount=20000.0)
        trf.action_submit()
        history = self.ApprovalHistory.search([
            ("request_type", "=", "nn.fund.transfer"),
            ("request_id", "=", trf.id),
        ])
        self.assertTrue(history)

    def test_transfer_ledger_entries_computed(self):
        trf = self._create_transfer(amount=30000.0)
        self._approve_fully(trf)
        self.assertEqual(len(trf.ledger_entry_ids), 3)

    def test_transfer_fund_account_no_cross_company(self):
        trf = self._create_transfer()
        self.assertEqual(
            trf.source_fund_account_id.company_id,
            trf.company_id,
        )


@tagged("fund_management", "audit")
class TestAuditLogPhase4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        cls.AuditLog = cls.env["nn.audit.log"]
        cls.Account = cls.env["nn.fund.account"]
        cls.Project = cls.env["nn.project"]
        cls.account = cls.Account.create({
            "name": "Audit Phase4 Account",
            "code": "AUD-P4",
            "type": "main",
            "company_id": cls.env.company.id,
        })
        cls.project = cls.Project.create({
            "name": "Audit Phase4 Project",
            "code": "AUD-P4-PRJ",
            "fund_account_id": cls.account.id,
            "company_id": cls.env.company.id,
        })

    def test_audit_log_transfer_action(self):
        log = self.AuditLog._log(
            model="nn.fund.transfer",
            res_id=1,
            action="transfer",
            reference="TRF-001",
            amount=50000.0,
            project_id=self.project.id,
            description="Test transfer action",
        )
        self.assertTrue(log)
        self.assertEqual(log.action, "transfer")

    def test_audit_log_transfer_action_selection(self):
        actions = dict(self.AuditLog._fields["action"].selection)
        self.assertIn("transfer", actions)
        self.assertEqual(actions["transfer"], "Transfer")
