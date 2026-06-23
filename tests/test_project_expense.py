from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "project", "expense")
class TestProjectExpense(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "PE Test Account",
            "code": "PET001",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "PE Project",
            "code": "PEPRJ",
            "fund_account_id": cls.account.id,
        })
        cls.project2 = cls.env["nn.project"].create({
            "name": "PE Project 2",
            "code": "PEPRJ2",
            "fund_account_id": cls.account.id,
        })
        cls.eh = cls.env["nn.expense.head"].create({
            "name": "PE Expense Head",
            "code": "PEEH",
            "project_id": cls.project.id,
        })

    # ── Project _compute_display_name ──
    def test_01_project_display_name(self):
        self.assertEqual(self.project.display_name, "[PEPRJ] PE Project")

    # ── Project _compute_project_balances ──
    def test_02_project_balances_zero_initially(self):
        self.assertEqual(self.project.allocated_amount, 0.0)
        self.assertEqual(self.project.spent_amount, 0.0)
        self.assertEqual(self.project.remaining_amount, 0.0)

    def test_03_project_balances_after_allocations(self):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": 100000.0,
            "credit": 0.0,
            "reference": "PE-SEED",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 25000.0,
            "purpose": "PE balance alloc",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        alloc.action_approve()
        self.project.invalidate_recordset()
        self.assertGreaterEqual(self.project.allocated_amount, 25000.0)

    def test_04_project_available_balance(self):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "project_id": self.project.id,
            "transaction_type": "incoming",
            "debit": 10000.0,
            "credit": 0.0,
            "reference": "PE-AVAIL",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.project.invalidate_recordset()
        self.assertGreater(self.project.available_balance, 0.0)

    # ── Project SQL constraint: code_unique_per_company ──
    def test_05_project_code_unique(self):
        with self.assertRaises(Exception):
            self.env["nn.project"].create({
                "name": "Duplicate Code",
                "code": "PEPRJ",
                "fund_account_id": self.account.id,
            })

    # ── Expense Head _compute_display_name ──
    def test_06_expense_head_display_name(self):
        self.assertEqual(self.eh.display_name, "[PEEH] PE Expense Head")

    # ── Expense Head _compute_expense_balances ──
    def test_07_expense_head_balances_zero_initially(self):
        self.assertEqual(self.eh.allocated_amount, 0.0)
        self.assertEqual(self.eh.spent_amount, 0.0)
        self.assertEqual(self.eh.remaining_amount, 0.0)

    # ── Expense Head SQL constraint: code_unique_per_project ──
    def test_08_expense_head_code_unique_per_project(self):
        with self.assertRaises(Exception):
            self.env["nn.expense.head"].create({
                "name": "Dup EH",
                "code": "PEEH",
                "project_id": self.project.id,
            })

    def test_09_expense_head_same_code_different_project_ok(self):
        eh2 = self.env["nn.expense.head"].create({
            "name": "PE EH2",
            "code": "PEEH",
            "project_id": self.project2.id,
        })
        self.assertTrue(eh2)
