from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "allocation")
class TestAllocationExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.group_gm = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.group_finance = cls.env.ref("nn_fund_management.group_finance_user")
        cls.gm_user = cls.env["res.users"].create({
            "name": "GM Tester",
            "login": "gm_ext",
            "password": "gm_ext",
            "groups_id": [(6, 0, [cls.group_gm.id])],
        })
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Alloc Ext Account",
            "code": "AEXT01",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "Test Project",
            "code": "TPROJ",
            "fund_account_id": cls.account.id,
        })
        cls.expense_head = cls.env["nn.expense.head"].create({
            "name": "Test EH",
            "code": "TEH",
            "project_id": cls.project.id,
        })

    def _credit_account(self, amount=100000.0):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": amount,
            "credit": 0.0,
            "reference": "SEED-ALLOC-EXT",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()

    # ── action_draft from cancelled ──
    def test_01_action_draft_from_cancelled(self):
        self._credit_account()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "purpose": "Draft test",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        alloc.action_cancel()
        self.assertEqual(alloc.state, "cancelled")
        alloc.action_draft()
        self.assertEqual(alloc.state, "draft")

    def test_02_action_draft_from_rejected(self):
        self._credit_account()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "purpose": "Reject draft test",
            "project_id": self.project.id,
        })
        matrix_line = self.env["nn.approval.matrix.line"].search([
            ("approval_group_id", "=", self.group_gm.id),
        ], limit=1)
        if not matrix_line:
            matrix = self.env["nn.approval.matrix"].create({
                "name": "Alloc Test",
                "request_type": "nn.fund.allocation",
                "min_amount": 0.0,
                "max_amount": 999999.0,
                "company_id": self.env.company.id,
            })
            matrix_line = self.env["nn.approval.matrix.line"].create({
                "matrix_id": matrix.id,
                "sequence": 10,
                "approval_group_id": self.group_gm.id,
                "name": "GM Step",
            })
        alloc.with_user(self.gm_user).action_submit()
        alloc.with_user(self.gm_user).action_reject()
        self.assertEqual(alloc.state, "rejected")
        alloc.action_draft()
        self.assertEqual(alloc.state, "draft")

    def test_03_action_draft_from_approved_blocked(self):
        self._credit_account()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "purpose": "Approved draft block",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        alloc.action_approve()
        with self.assertRaises(ValidationError):
            alloc.action_draft()

    # ── SQL constraint: amount_positive ──
    def test_04_negative_amount_blocked(self):
        with self.assertRaises(Exception):
            self.env["nn.fund.allocation"].create({
                "fund_account_id": self.account.id,
                "amount": -100.0,
                "purpose": "Negative",
            })

    def test_05_zero_amount_blocked(self):
        with self.assertRaises(Exception):
            self.env["nn.fund.allocation"].create({
                "fund_account_id": self.account.id,
                "amount": 0.0,
                "purpose": "Zero",
            })

    # ── SQL constraint: request_number_unique_per_company ──
    def test_06_duplicate_request_number_blocked(self):
        self._credit_account()
        self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 500.0,
            "purpose": "First",
            "request_number": "DUP-ALLOC-001",
            "project_id": self.project.id,
        })
        with self.assertRaises(Exception):
            self.env["nn.fund.allocation"].create({
                "fund_account_id": self.account.id,
                "amount": 600.0,
                "purpose": "Second",
                "request_number": "DUP-ALLOC-001",
                "project_id": self.project.id,
            })

    # ── _onchange_expense_head_id sets project ──
    def test_07_onchange_expense_head_sets_project(self):
        alloc = self.env["nn.fund.allocation"].new({
            "fund_account_id": self.account.id,
            "amount": 100.0,
            "purpose": "Onchange test",
        })
        alloc.expense_head_id = self.expense_head
        alloc._onchange_expense_head_id()
        self.assertEqual(alloc.project_id.id, self.project.id)

    # ── _notify_matrix_line_approvers creates activities ──
    def test_08_notify_matrix_line_approvers_creates_activities(self):
        self._credit_account()
        matrix = self.env["nn.approval.matrix"].create({
            "name": "Notify Test",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 999999.0,
            "company_id": self.env.company.id,
        })
        line = self.env["nn.approval.matrix.line"].create({
            "matrix_id": matrix.id,
            "sequence": 10,
            "approval_group_id": self.group_gm.id,
            "name": "GM Step",
        })
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "purpose": "Notify test",
            "project_id": self.project.id,
        })
        alloc._notify_matrix_line_approvers(line)
        activities = self.env["mail.activity"].search([
            ("res_id", "=", alloc.id),
            ("res_model", "=", "nn.fund.allocation"),
        ])
        self.assertTrue(activities)
