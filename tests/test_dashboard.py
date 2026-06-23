from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "fund_management", "dashboard")
class TestDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Dash Account",
            "code": "DASH01",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "Dash Project",
            "code": "DASHP",
            "fund_account_id": cls.account.id,
        })
        cls.expense_head = cls.env["nn.expense.head"].create({
            "name": "Dash EH",
            "code": "DASHEH",
            "project_id": cls.project.id,
        })

    def _seed(self, amount=50000.0):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": amount,
            "credit": 0.0,
            "reference": "DASH-SEED",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()

    # ── Fund Dashboard ──
    def test_01_fund_dashboard_default_get(self):
        self._seed()
        dash = self.env["nn.fund.dashboard"].default_get([])
        self.assertIn("total_funds_received", dash)
        self.assertIn("available_balance", dash)
        self.assertIn("fund_accounts_count", dash)
        self.assertIn("active_projects_count", dash)
        self.assertGreaterEqual(dash["total_funds_received"], 50000.0)
        self.assertGreaterEqual(dash["fund_accounts_count"], 1)

    def test_02_fund_dashboard_with_pending_allocations(self):
        self._seed()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "purpose": "Dash alloc",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        dash = self.env["nn.fund.dashboard"].default_get([])
        self.assertGreaterEqual(dash["pending_allocations_count"], 1)
        self.assertGreaterEqual(dash["pending_approvals_count"], 1)

    def test_03_fund_dashboard_action_open(self):
        dash = self.env["nn.fund.dashboard"]
        result = dash.action_open_dashboard()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "nn.fund.dashboard")

    # ── Project Dashboard ──
    def test_04_project_dashboard_default_get(self):
        proj_dash = self.env["nn.project.dashboard"].default_get([])
        self.assertIn("currency_id", proj_dash)

    # ── Expense Head Dashboard ──
    def test_05_expense_head_dashboard_default_get(self):
        eh_dash = self.env["nn.expense.head.dashboard"].default_get([])
        self.assertIn("currency_id", eh_dash)

    # ── Recent Activity ──
    def test_06_recent_activity_default_get(self):
        activity = self.env["nn.recent.activity"].default_get([])
        self.assertIn("currency_id", activity)

    # ── Dashboard reflects project count ──
    def test_07_dashboard_project_count(self):
        dash = self.env["nn.fund.dashboard"].default_get([])
        self.assertGreaterEqual(dash["active_projects_count"], 1)
