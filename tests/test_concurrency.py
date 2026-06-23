from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "concurrency")
class TestConcurrency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Concurrency Account",
            "code": "CONC01",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "Concurrency Project",
            "code": "CONCPRJ",
            "fund_account_id": cls.account.id,
        })

    def _seed_balance(self, amount=100000.0):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": amount,
            "credit": 0.0,
            "reference": "CONC-SEED",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()

    # ── Double-spending prevention: balance check blocks overspend ──
    def test_01_double_spend_blocked_by_balance_check(self):
        self._seed_balance(1000.0)
        alloc1 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 800.0,
            "purpose": "First alloc",
            "project_id": self.project.id,
        })
        alloc1.action_submit()
        self.account.invalidate_recordset()
        alloc2 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 500.0,
            "purpose": "Second alloc - should fail",
            "project_id": self.project.id,
        })
        with self.assertRaises(ValidationError):
            alloc2.action_submit()

    # ── Hold prevents subsequent submission ──
    def test_02_hold_prevents_second_approval(self):
        self._seed_balance(5000.0)
        alloc1 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "First hold test",
            "project_id": self.project.id,
        })
        alloc1.action_submit()
        self.account.invalidate_recordset()
        alloc2 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "Second hold test - should fail",
            "project_id": self.project.id,
        })
        with self.assertRaises(ValidationError):
            alloc2.action_submit()

    # ── Reject releases hold so second can proceed ──
    def test_03_reject_releases_hold_for_second_alloc(self):
        self._seed_balance(5000.0)
        alloc1 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "First - will be rejected",
            "project_id": self.project.id,
        })
        alloc1.action_submit()
        alloc1.action_reject()
        self.account.invalidate_recordset()
        alloc2 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "Second - should succeed after reject",
            "project_id": self.project.id,
        })
        alloc2.action_submit()
        self.assertEqual(alloc2.state, "submitted")

    # ── Cancel releases hold ──
    def test_04_cancel_releases_hold_for_second(self):
        self._seed_balance(5000.0)
        alloc1 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "First - will be cancelled",
            "project_id": self.project.id,
        })
        alloc1.action_submit()
        alloc1.action_cancel()
        self.account.invalidate_recordset()
        alloc2 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "purpose": "Second - should succeed after cancel",
            "project_id": self.project.id,
        })
        alloc2.action_submit()
        self.assertEqual(alloc2.state, "submitted")

    # ── Sequential holds across allocation and transfer ──
    def test_05_hold_from_allocation_and_transfer_combined(self):
        self._seed_balance(10000.0)
        dest_account = self.env["nn.fund.account"].create({
            "name": "Dest Concurrency",
            "code": "DCONC",
            "currency_id": self.currency.id,
        })
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 7000.0,
            "purpose": "Alloc for concurrency",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        self.account.invalidate_recordset()
        transfer = self.env["nn.fund.transfer"].create({
            "source_project_id": self.project.id,
            "destination_project_id": self.env["nn.project"].create({
                "name": "Dest Proj",
                "code": "DPROJ",
                "fund_account_id": dest_account.id,
            }).id,
            "amount": 5000.0,
            "reason": "Concurrent transfer",
        })
        with self.assertRaises(ValidationError):
            transfer.action_submit()

    # ── Available balance formula integrity after multi-step ──
    def test_06_balance_integrity_after_multi_step(self):
        self._seed_balance(10000.0)
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 6000.0,
            "purpose": "Balance integrity",
            "project_id": self.project.id,
        })
        self.account.invalidate_recordset()
        bal_before = self.account.available_balance
        alloc.action_submit()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.available_balance, bal_before - 6000.0)
        alloc.action_approve()
        self.account.invalidate_recordset()
        self.assertEqual(self.account.available_balance, bal_before - 6000.0)

    # ── Requisition and allocation hold interaction ──
    def test_07_requisition_and_allocation_hold_interaction(self):
        self._seed_balance(10000.0)
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 4000.0,
            "purpose": "Alloc for interaction",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        self.account.invalidate_recordset()
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 4000.0,
        })
        with self.assertRaises(ValidationError):
            req.action_submit()

    # ── Bill cannot exceed remaining after partial ──
    def test_08_bill_exact_remaining_works(self):
        self._seed_balance(10000.0)
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 5000.0,
        })
        req.action_submit()
        req.action_approve()
        bill1 = self.env["nn.fund.bill"].create({
            "requisition_id": req.id,
            "amount": 3000.0,
            "vendor_name": "Vendor A",
        })
        bill1.action_post()
        req.invalidate_recordset()
        self.assertEqual(req.remaining_billable_amount, 2000.0)
        bill2 = self.env["nn.fund.bill"].create({
            "requisition_id": req.id,
            "amount": 2000.0,
            "vendor_name": "Vendor B",
        })
        bill2.action_post()
        req.invalidate_recordset()
        self.assertEqual(req.remaining_billable_amount, 0.0)
