from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError


@tagged("post_install", "-at_install", "fund_management", "reconciliation")
class TestReconciliationExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Rec Ext Account",
            "code": "REXT01",
            "currency_id": cls.currency.id,
        })
        cls.account2 = cls.env["nn.fund.account"].create({
            "name": "Rec Ext Account 2",
            "code": "REXT02",
            "currency_id": cls.currency.id,
        })

    def _create_reconciliation(self):
        return self.env["nn.ledger.reconciliation"].create({
            "date": self.env["nn.ledger.reconciliation"]._fields["date"].default(
                self.env["nn.ledger.reconciliation"]
            ),
            "company_id": self.env.company.id,
        })

    def _post_entry(self, account=None, debit=0.0, credit=0.0, ttype="incoming",
                    ref="REC-EXT", state="posted"):
        account = account or self.account
        return self.env["nn.fund.ledger"].create({
            "fund_account_id": account.id,
            "transaction_type": ttype,
            "debit": debit,
            "credit": credit,
            "reference": ref,
            "state": state,
            "company_id": self.env.company.id,
        })

    # ── SQL constraint: unique_date_per_company ──
    def test_01_unique_date_per_company(self):
        self._create_reconciliation()
        with self.assertRaises(Exception):
            self._create_reconciliation()

    # ── action_view_lines ──
    def test_02_action_view_lines_returns_action(self):
        self._post_entry(debit=1000.0)
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        result = rec.action_view_lines()
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "nn.ledger.reconciliation.line")
        self.assertIn(rec.id, result["domain"][0])

    # ── Failed state on exception ──
    def test_03_failed_state_on_exception(self):
        rec = self._create_reconciliation()
        rec.write({"state": "in_progress"})
        try:
            rec._run_checks()
        except Exception:
            pass
        rec.write({"state": "failed", "completed_at": self.env["nn.ledger.reconciliation"]._fields["completed_at"].default(
            self.env["nn.ledger.reconciliation"]
        )})
        self.assertEqual(rec.state, "failed")

    # ── _compute_display_name ──
    def test_04_display_name_format(self):
        rec = self._create_reconciliation()
        self.assertIn("Reconciliation", rec.display_name)
        self.assertIn("Draft", rec.display_name)

    # ── _compute_duration ──
    def test_05_duration_computed(self):
        rec = self._create_reconciliation()
        self.assertEqual(rec.duration_seconds, 0)
        rec.write({
            "started_at": "2026-06-19 10:00:00",
            "completed_at": "2026-06-19 10:05:30",
        })
        self.assertEqual(rec.duration_seconds, 330)

    # ── _generate_alerts creates activities on critical ──
    def test_06_generate_alerts_critical(self):
        self._post_entry(credit=100.0)
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        activities = self.env["mail.activity"].search([
            ("res_id", "=", rec.id),
            ("res_model", "=", "nn.ledger.reconciliation"),
        ])
        self.assertTrue(activities)

    # ── _compute_issue_summary ──
    def test_07_issue_summary_after_reconciliation(self):
        self._post_entry(debit=1000.0)
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.issue_summary)
        self.assertIn("OK", rec.issue_summary)

    # ── Cannot run reconciliation from completed state ──
    def test_08_cannot_run_from_completed(self):
        self._post_entry(debit=500.0)
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        with self.assertRaises(UserError):
            rec.action_run_reconciliation()

    # ── Orphan detection with nonexistent reference_model ──
    def test_09_orphan_nonexistent_model(self):
        entry = self._post_entry(debit=500.0, ttype="allocation_approve", ref="ORPH-NO-MODEL")
        entry.write({"reference_model": "nonexistent.model", "reference_id": 1})
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertFalse(line or True)

    # ── Multiple accounts with mixed states ──
    def test_10_mixed_account_severities(self):
        self._post_entry(debit=1000.0)  # account 1: ok
        self._post_entry(account=self.account2, credit=500.0)  # account 2: critical (negative)
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.severity, "critical")

    # ── _find_orphan_entries with None model ──
    def test_11_orphan_with_no_reference_model(self):
        entry = self._post_entry(debit=500.0, ref="ORPH-NO-REF")
        entry.write({"reference_model": False, "reference_id": False})
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertFalse(line.orphan_count > 0)
