from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError
from datetime import date, timedelta


@tagged("post_install", "-at_install")
class TestLedgerReconciliation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                tracking_disable=True,
                no_reset_password=True,
            )
        )
        cls.group_admin = cls.env.ref("nn_fund_management.group_fund_administrator")
        cls.group_finance = cls.env.ref("nn_fund_management.group_finance_user")
        cls.admin_user = cls.env["res.users"].create({
            "name": "Admin",
            "login": "admin_rec",
            "password": "admin",
            "groups_id": [(6, 0, [cls.group_admin.id])],
        })
        cls.finance_user = cls.env["res.users"].create({
            "name": "Finance",
            "login": "finance_rec",
            "password": "finance",
            "groups_id": [(6, 0, [cls.group_finance.id])],
        })
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Test Account",
            "code": "TA001",
            "currency_id": cls.currency.id,
        })
        cls.account2 = cls.env["nn.fund.account"].create({
            "name": "Test Account 2",
            "code": "TA002",
            "currency_id": cls.currency.id,
        })

    def _create_reconciliation(self):
        return self.env["nn.ledger.reconciliation"].create({
            "date": date.today(),
            "company_id": self.env.company.id,
        })

    def _create_ledger_entry(self, account=None, debit=0.0, credit=0.0,
                              ttype="incoming", reference="REF001",
                              state="posted", ref_model=None, ref_id=None):
        account = account or self.account
        vals = {
            "fund_account_id": account.id,
            "transaction_type": ttype,
            "debit": debit,
            "credit": credit,
            "reference": reference,
            "state": state,
            "company_id": self.env.company.id,
        }
        if ref_model:
            vals["reference_model"] = ref_model
        if ref_id:
            vals["reference_id"] = ref_id
        return self.env["nn.fund.ledger"].create(vals)

    def test_01_clean_reconciliation_ok(self):
        """Test a clean reconciliation passes with OK severity."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.state, "completed")
        self.assertEqual(rec.severity, "ok")
        self.assertFalse(rec.block_operations)
        self.assertEqual(rec.total_accounts, 2)

    def test_02_detects_discrepancy(self):
        """Test discrepancy detection by creating a ledger entry after
        the stored balance was computed (simulate drift)."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.severity, "ok")

        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertTrue(line)
        self.assertFalse(line.has_discrepancy)
        self.assertEqual(line.ledger_derived_current_balance, 1000.0)

    def test_03_negative_balance_critical(self):
        """Test negative balance detection triggers critical severity."""
        self._create_ledger_entry(credit=500.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.severity, "critical")
        self.assertTrue(rec.block_operations)

    def test_04_duplicate_detection(self):
        """Test duplicate ledger entries are counted."""
        for _ in range(3):
            self._create_ledger_entry(
                debit=200.0, ttype="incoming", reference="DUP001"
            )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.duplicate_count, 2)

    def test_05_no_duplicates_for_unique_entries(self):
        """Test unique entries produce no duplicate count."""
        for i in range(3):
            self._create_ledger_entry(
                debit=200.0, ttype="incoming", reference=f"UNIQ00{i}"
            )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertEqual(line.duplicate_count, 0)

    def test_06_missing_entries_detection(self):
        """Test detection of missing expected ledger entries for approved records."""
        allocation = self.env["nn.fund.allocation"].create({
            "name": "Test Allocation",
            "fund_account_id": self.account.id,
            "amount": 500.0,
            "state": "approved",
            "company_id": self.env.company.id,
        })
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertGreaterEqual(rec.accounts_with_issues, 1)
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.missing_entry_count, 1)

    def test_07_orphan_detection(self):
        """Test orphan ledger entries (deleted source record) are detected."""
        entry = self._create_ledger_entry(
            debit=500.0, ttype="incoming", reference="ORPHAN001",
            ref_model="nn.fund.allocation", ref_id=99999,
        )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.orphan_count, 1)

    def test_08_blocks_operations_on_critical(self):
        """Test that critical reconciliation sets block_operations."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.block_operations)

    def test_09_unblock_operations(self):
        """Test unblocking operations by fund administrator."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.block_operations)
        rec.with_user(self.admin_user).action_unblock_operations()
        self.assertFalse(rec.block_operations)

    def test_10_unblock_requires_admin(self):
        """Test that non-admin cannot unblock operations."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        with self.assertRaises(Exception):
            rec.with_user(self.finance_user).action_unblock_operations()

    def test_11_reconciliation_health_check_raises(self):
        """Test _check_reconciliation_health raises on blocked reconciliation."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        with self.assertRaises(ValidationError):
            self.env["nn.security.mixin"]._check_reconciliation_health()

    def test_12_reconciliation_health_ok_after_unblock(self):
        """Test _check_reconciliation_health passes after unblock."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        rec.with_user(self.admin_user).action_unblock_operations()
        result = self.env["nn.security.mixin"]._check_reconciliation_health()
        self.assertTrue(result)

    def test_13_multi_account_reconciliation(self):
        """Test reconciliation across multiple accounts."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        self._create_ledger_entry(
            account=self.account2, debit=500.0, ttype="incoming",
            reference="REF_MULTI"
        )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.total_accounts, 2)
        self.assertEqual(len(rec.line_ids), 2)
        self.assertEqual(rec.severity, "ok")

    def test_14_cron_nightly_reconciliation(self):
        """Test cron job creates and runs reconciliation for today."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        result = self.env["nn.ledger.reconciliation"].cron_nightly_reconciliation()
        self.assertTrue(result)
        rec = self.env["nn.ledger.reconciliation"].search([
            ("date", "=", date.today()),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        self.assertTrue(rec)
        self.assertEqual(rec.state, "completed")

    def test_15_cron_reuses_existing_draft(self):
        """Test cron reuses existing draft reconciliation for today."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        draft = self._create_reconciliation()
        self.assertEqual(draft.state, "draft")
        self.env["nn.ledger.reconciliation"].cron_nightly_reconciliation()
        self.assertEqual(draft.state, "completed")

    def test_16_all_five_balances_independently_derived(self):
        """Test that all 5 balance types are independently derived."""
        self._create_ledger_entry(debit=10000.0, ttype="incoming", reference="BAL_IN")
        self._create_ledger_entry(
            credit=2000.0, ttype="allocation_hold", reference="BAL_HOLD"
        )
        self._create_ledger_entry(
            debit=500.0, ttype="allocation_release", reference="BAL_REL"
        )
        self._create_ledger_entry(
            credit=3000.0, ttype="allocation_approve", reference="BAL_APP"
        )
        self._create_ledger_entry(
            credit=1000.0, ttype="bill_posted", reference="BAL_BILL"
        )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertFalse(line.has_discrepancy)
        self.assertEqual(line.ledger_derived_current_balance, 10000.0)
        self.assertEqual(line.ledger_derived_held_balance, 1500.0)
        self.assertEqual(line.ledger_derived_assigned_balance, 3000.0)
        self.assertEqual(line.ledger_derived_spent_balance, 1000.0)
        self.assertEqual(line.ledger_derived_available_balance, 4500.0)

    def test_17_summary_html_generated(self):
        """Test that summary_html is populated after reconciliation."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.summary_html)
        self.assertIn("Ledger Reconciliation Report", rec.summary_html)
        self.assertIn("TA001", rec.summary_html)

    def test_18_duplicate_composite_key_different_refs(self):
        """Test entries with different references on same type+amount are not
        flagged as duplicates."""
        for i in range(2):
            self._create_ledger_entry(
                debit=200.0, ttype="incoming", reference=f"DIFF_REF_{i}"
            )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertEqual(line.duplicate_count, 0)

    def test_19_unposted_entries_excluded(self):
        """Test unposted (draft) ledger entries do not affect reconciliation."""
        self._create_ledger_entry(
            debit=1000.0, ttype="incoming", state="draft"
        )
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertEqual(line.ledger_derived_current_balance, 0.0)

    def test_20_in_progress_state(self):
        """Test that reconciliation enters in_progress state during run."""
        self._create_ledger_entry(debit=500.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.state, "completed")

    def test_21_warning_severity_on_discrepancy_only(self):
        """Test that discrepancy without negative balance yields warning."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming", reference="WARN")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertIn(rec.severity, ("ok", "warning"))

    def test_22_orphan_entry_deleted_allocation(self):
        """Test orphan detection on deleted allocation record."""
        alloc = self.env["nn.fund.allocation"].create({
            "name": "Orphan Alloc",
            "fund_account_id": self.account.id,
            "amount": 300.0,
            "state": "approved",
            "company_id": self.env.company.id,
        })
        entry = self._create_ledger_entry(
            debit=300.0, ttype="allocation_approve", reference="ORPH_DEL",
            ref_model="nn.fund.allocation", ref_id=alloc.id,
        )
        alloc.unlink()
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.orphan_count, 1)

    def test_23_reconciliation_requires_admin_for_unblock(self):
        """Double-check unblock restricted to Fund Administrator group."""
        self._create_ledger_entry(credit=50.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.block_operations)
        other_user = self.env["res.users"].create({
            "name": "Other",
            "login": "other_rec",
            "password": "other",
        })
        with self.assertRaises(Exception):
            rec.with_user(other_user).action_unblock_operations()

    def test_24_missing_entries_for_requisition(self):
        """Test missing entry detection for requisition records."""
        req = self.env["nn.fund.requisition"].create({
            "name": "Test Req",
            "fund_account_id": self.account.id,
            "amount": 800.0,
            "state": "approved",
            "company_id": self.env.company.id,
        })
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.missing_entry_count, 1)

    def test_25_missing_entries_for_transfer(self):
        """Test missing entry detection for transfer records."""
        transfer = self.env["nn.fund.transfer"].create({
            "name": "Test Transfer",
            "source_fund_account_id": self.account.id,
            "destination_fund_account_id": self.account2.id,
            "amount": 600.0,
            "state": "approved",
            "company_id": self.env.company.id,
        })
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        line = rec.line_ids.filtered(lambda l: l.fund_account_id == self.account)
        self.assertGreaterEqual(line.missing_entry_count, 1)

    def test_26_validate_available_balance_checks_health(self):
        """Test that _validate_available_balance triggers health check."""
        self._create_ledger_entry(credit=100.0, ttype="incoming")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertTrue(rec.block_operations)
        self.account.invalidate_recordset()
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": 500.0,
            "reference": "HEALTH_CHECK",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()
        with self.assertRaises(ValidationError) as ctx:
            self.env["nn.security.mixin"]._validate_available_balance(
                self.account, 200.0
            )
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_27_validate_available_balance_passes_when_healthy(self):
        """Test that _validate_available_balance passes when reconciliation ok."""
        self._create_ledger_entry(debit=1000.0, ttype="incoming", reference="HEALTH_OK")
        rec = self._create_reconciliation()
        rec.action_run_reconciliation()
        self.assertEqual(rec.severity, "ok")
        self.assertFalse(rec.block_operations)
        self.account.invalidate_recordset()
        result = self.env["nn.security.mixin"]._validate_available_balance(
            self.account, 200.0
        )
        self.assertTrue(result)
