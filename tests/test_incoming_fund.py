from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "incoming")
class TestIncomingFundExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Incoming Test Account",
            "code": "INC001",
            "currency_id": cls.currency.id,
        })
        cls.closed_account = cls.env["nn.fund.account"].create({
            "name": "Closed Account",
            "code": "CLS001",
            "currency_id": cls.currency.id,
            "is_closed": True,
        })

    # ── SQL constraint: reference_unique_per_company ──
    def test_01_duplicate_reference_blocked(self):
        self.env["nn.incoming.fund"].create({
            "reference": "DUP-REF-001",
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "source_type": "donor",
        })
        with self.assertRaises(Exception):
            self.env["nn.incoming.fund"].create({
                "reference": "DUP-REF-001",
                "fund_account_id": self.account.id,
                "amount": 2000.0,
                "source_type": "donor",
            })

    # ── SQL constraint: amount_positive ──
    def test_02_negative_amount_blocked(self):
        with self.assertRaises(Exception):
            self.env["nn.incoming.fund"].create({
                "reference": "NEG-001",
                "fund_account_id": self.account.id,
                "amount": -500.0,
                "source_type": "donor",
            })

    def test_03_zero_amount_blocked(self):
        with self.assertRaises(Exception):
            self.env["nn.incoming.fund"].create({
                "reference": "ZERO-001",
                "fund_account_id": self.account.id,
                "amount": 0.0,
                "source_type": "donor",
            })

    # ── _check_fund_account_active — closed account ──
    def test_04_confirm_to_closed_account_blocked(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "CLOSED-001",
            "fund_account_id": self.closed_account.id,
            "amount": 1000.0,
            "source_type": "donor",
        })
        with self.assertRaises(ValidationError):
            fund.action_confirm()

    # ── action_reverse full workflow ──
    def test_05_reverse_confirmed_incoming_fund(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "REV-001",
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "source_type": "donor",
        })
        fund.action_confirm()
        self.assertEqual(fund.state, "confirmed")
        self.assertTrue(fund.ledger_entry_id)
        self.account.invalidate_recordset()
        balance_before_reverse = self.account.current_balance
        fund.action_reverse()
        self.assertEqual(fund.state, "reversed")
        self.assertTrue(fund.reversal_ledger_entry_id)
        self.account.invalidate_recordset()
        self.assertEqual(self.account.current_balance, balance_before_reverse - 5000.0)

    def test_06_cannot_reverse_draft(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "REV-DRAFT",
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "source_type": "donor",
        })
        with self.assertRaises(ValidationError):
            fund.action_reverse()

    def test_07_cannot_reverse_reversed(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "REV-REV",
            "fund_account_id": self.account.id,
            "amount": 1000.0,
            "source_type": "donor",
        })
        fund.action_confirm()
        fund.action_reverse()
        with self.assertRaises(ValidationError):
            fund.action_reverse()

    # ── action_confirm from draft (not just pending_verification) ──
    def test_08_confirm_from_draft(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "DIRECT-CONF",
            "fund_account_id": self.account.id,
            "amount": 3000.0,
            "source_type": "donor",
        })
        fund.action_confirm()
        self.assertEqual(fund.state, "confirmed")
        self.account.invalidate_recordset()
        self.assertGreater(self.account.current_balance, 0.0)

    # ── ledger entry state = posted after confirm ──
    def test_09_ledger_entry_posted_after_confirm(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "LEDGER-POST",
            "fund_account_id": self.account.id,
            "amount": 2000.0,
            "source_type": "donor",
        })
        fund.action_confirm()
        self.assertEqual(fund.ledger_entry_id.state, "posted")

    # ── verify from pending_verification matches action_confirm behavior ──
    def test_10_verify_same_as_confirm_from_pending(self):
        fund = self.env["nn.incoming.fund"].create({
            "reference": "VERIFY-TEST",
            "fund_account_id": self.account.id,
            "amount": 1500.0,
            "source_type": "donor",
            "state": "pending_verification",
        })
        fund.action_verify()
        self.assertEqual(fund.state, "confirmed")
