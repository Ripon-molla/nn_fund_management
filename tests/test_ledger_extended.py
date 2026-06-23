from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "ledger")
class TestLedgerExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Ledger Ext Account",
            "code": "LEXT01",
            "currency_id": cls.currency.id,
        })

    def _create_entry(self, state="draft", debit=100.0, credit=0.0, ttype="incoming"):
        return self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": ttype,
            "debit": debit,
            "credit": credit,
            "reference": "LEXT-REF",
            "state": state,
            "company_id": self.env.company.id,
        })

    # ── action_post transitions draft → posted ──
    def test_01_action_post_transitions_state(self):
        entry = self._create_entry(state="draft")
        self.assertEqual(entry.state, "draft")
        entry.action_post()
        self.assertEqual(entry.state, "posted")

    def test_02_action_post_already_posted_blocked(self):
        entry = self._create_entry(state="posted")
        with self.assertRaises(ValidationError):
            entry.action_post()

    # ── action_reverse on posted entry ──
    def test_03_action_reverse_creates_reversal(self):
        entry = self._create_entry(state="posted", debit=500.0)
        initial_balance = self.account.current_balance
        reversal = entry.action_reverse()
        self.assertTrue(reversal)
        self.assertEqual(reversal.state, "posted")
        self.assertEqual(reversal.transaction_type, entry.transaction_type)
        self.account.invalidate_recordset()
        self.assertEqual(self.account.current_balance, initial_balance - 500.0)

    def test_04_action_reverse_draft_blocked(self):
        entry = self._create_entry(state="draft")
        with self.assertRaises(ValidationError):
            entry.action_reverse()

    # ── _check_transaction_direction ──
    def test_05_incoming_must_be_debit(self):
        with self.assertRaises(ValidationError):
            self._create_entry(debit=0.0, credit=100.0, ttype="incoming")

    def test_06_bill_posted_must_be_credit(self):
        with self.assertRaises(ValidationError):
            self._create_entry(debit=100.0, credit=0.0, ttype="bill_posted")

    def test_07_allocation_hold_must_be_credit(self):
        with self.assertRaises(ValidationError):
            self._create_entry(debit=100.0, credit=0.0, ttype="allocation_hold")

    # ── Write operation blocked on posted entry ──
    def test_08_write_blocked_on_posted(self):
        entry = self._create_entry(state="posted")
        with self.assertRaises(ValidationError):
            entry.write({"reference": "CHANGED"})

    # ── Unlink operation blocked on posted entry ──
    def test_09_unlink_blocked_on_posted(self):
        entry = self._create_entry(state="posted")
        with self.assertRaises(ValidationError):
            entry.unlink()
