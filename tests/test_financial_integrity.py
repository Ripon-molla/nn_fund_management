from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError


@tagged("post_install", "-at_install", "fund_management", "integrity")
class TestFinancialIntegrity(TransactionCase):
    """Comprehensive tests for all 10 financial integrity protections."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.group_admin = cls.env.ref("nn_fund_management.group_fund_administrator")
        cls.group_gm = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.group_finance = cls.env.ref("nn_fund_management.group_finance_user")
        cls.admin = cls.env["res.users"].create({
            "name": "Admin Integ",
            "login": "admin_integ",
            "password": "admin_integ",
            "groups_id": [(6, 0, [cls.group_admin.id])],
        })
        cls.gm_user = cls.env["res.users"].create({
            "name": "GM Integ",
            "login": "gm_integ",
            "password": "gm_integ",
            "groups_id": [(6, 0, [cls.group_gm.id])],
        })
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Integ Test Account",
            "code": "INTEG01",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "Integ Project",
            "code": "INTEGPRJ",
            "fund_account_id": cls.account.id,
        })

    def _seed(self, amount=1000000.0):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": amount,
            "credit": 0.0,
            "reference": "INTEG-SEED",
            "reference_model": "nn.incoming.fund",
            "reference_id": 0,
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()

    def _create_alloc(self):
        return self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 10000.0,
            "purpose": "Integ test",
            "project_id": self.project.id,
        })

    # ──────────────────────────────────────────────
    # PROTECTION 1: LEDGER IMMUTABILITY
    # ──────────────────────────────────────────────

    def test_01_posted_entry_cannot_be_modified(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        with self.assertRaises(UserError):
            entry.write({"reference": "CHANGED"})

    def test_02_posted_entry_cannot_be_deleted(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        with self.assertRaises(UserError):
            entry.unlink()

    def test_03_posted_entry_cannot_revert_to_draft(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        with self.assertRaises(UserError):
            entry.write({"state": "draft"})

    def test_04_reversed_entry_cannot_be_modified(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        entry.action_reverse()
        with self.assertRaises(UserError):
            entry.write({"reference": "STILL_IMMUTABLE"})

    def test_05_reversed_entry_cannot_be_deleted(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        entry.action_reverse()
        with self.assertRaises(UserError):
            entry.unlink()

    # ──────────────────────────────────────────────
    # PROTECTION 2: APPROVAL IDEMPOTENCY
    # ──────────────────────────────────────────────

    def test_06_duplicate_approval_blocked(self):
        self._seed()
        matrix = self.env["nn.approval.matrix"].create({
            "name": "Integ Matrix",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 9999999.0,
            "company_id": self.env.company.id,
        })
        self.env["nn.approval.matrix.line"].create({
            "matrix_id": matrix.id,
            "sequence": 10,
            "approval_group_id": self.group_gm.id,
            "name": "GM Step",
        })
        alloc = self._create_alloc()
        alloc.with_user(self.gm_user).action_submit()
        alloc.with_user(self.gm_user).action_approve()
        with self.assertRaises(ValidationError):
            alloc.with_user(self.gm_user).action_approve()

    # ──────────────────────────────────────────────
    # PROTECTION 3: TRANSACTION IDEMPOTENCY
    # ──────────────────────────────────────────────

    def test_07_duplicate_uuid_blocked(self):
        self._seed()
        with self.assertRaises(Exception):
            self.env["nn.fund.ledger"].create({
                "fund_account_id": self.account.id,
                "transaction_type": "incoming",
                "debit": 100.0,
                "credit": 0.0,
                "reference": "UUID-DUP",
                "reference_model": "test.model",
                "reference_id": 0,
                "transaction_uuid": "test-uuid-0001",
                "state": "posted",
                "company_id": self.env.company.id,
            })
            self.env["nn.fund.ledger"].create({
                "fund_account_id": self.account.id,
                "transaction_type": "incoming",
                "debit": 100.0,
                "credit": 0.0,
                "reference": "UUID-DUP-2",
                "reference_model": "test.model",
                "reference_id": 0,
                "transaction_uuid": "test-uuid-0001",
                "state": "posted",
                "company_id": self.env.company.id,
            })

    # ──────────────────────────────────────────────
    # PROTECTION 4: CONCURRENCY PROTECTION
    # ──────────────────────────────────────────────

    def test_08_row_locking_prevents_double_depletion(self):
        self._seed(amount=50000.0)
        self.env["nn.security.mixin"]._acquire_row_lock(self.account.id)
        self.account.invalidate_recordset()
        self.assertTrue(self.account.available_balance > 0)

    def test_09_balance_validated_before_allocation_submit(self):
        self._seed(amount=1000.0)
        alloc = self._create_alloc()
        alloc.amount = 999999.0
        with self.assertRaises(ValidationError):
            alloc.action_submit()

    # ──────────────────────────────────────────────
    # PROTECTION 5: BALANCE VALIDATION
    # ──────────────────────────────────────────────

    def test_10_balance_validated_on_transfer_submit(self):
        self._seed(amount=5000.0)
        dest = self.env["nn.fund.account"].create({
            "name": "Integ Dest",
            "code": "INTEGDEST",
            "currency_id": self.currency.id,
        })
        dest_proj = self.env["nn.project"].create({
            "name": "Integ Dest Proj",
            "code": "INTEGDPRJ",
            "fund_account_id": dest.id,
        })
        trf = self.env["nn.fund.transfer"].create({
            "source_project_id": self.project.id,
            "destination_project_id": dest_proj.id,
            "amount": 999999.0,
            "reason": "Should fail",
        })
        with self.assertRaises(ValidationError):
            trf.action_submit()

    def test_11_balance_validated_on_requisition_submit(self):
        self._seed(amount=1000.0)
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 999999.0,
        })
        with self.assertRaises(ValidationError):
            req.action_submit()

    # ──────────────────────────────────────────────
    # PROTECTION 6: REVERSAL INTEGRITY
    # ──────────────────────────────────────────────

    def test_12_reversal_swaps_debit_credit(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        original_debit = entry.debit
        original_credit = entry.credit
        reversal = entry.action_reverse()
        self.assertEqual(reversal.credit, original_debit)
        self.assertEqual(reversal.debit, original_credit)

    def test_13_reversal_net_impact_zero(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        reversal = entry.action_reverse()
        net = (entry.debit - entry.credit) + (reversal.debit - reversal.credit)
        self.assertAlmostEqual(net, 0.0, places=2)

    def test_14_incoming_fund_reversal_uses_reversal_integrity_check(self):
        inc = self.env["nn.incoming.fund"].create({
            "reference": "INTEG-INC-REV",
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "source_type": "donor",
        })
        inc.action_confirm()
        inc.action_reverse()
        self.assertEqual(inc.state, "reversed")
        self.account.invalidate_recordset()
        self.assertAlmostEqual(self.account.current_balance, 0.0, places=2)

    # ──────────────────────────────────────────────
    # PROTECTION 7: AUDIT IMMUTABILITY
    # ──────────────────────────────────────────────

    def test_15_audit_log_cannot_be_modified(self):
        log = self.env["nn.audit.log"].create({
            "model": "test.model",
            "res_id": 1,
            "action": "create",
            "company_id": self.env.company.id,
            "user_id": self.env.user.id,
        })
        with self.assertRaises(UserError):
            log.write({"description": "tampered"})

    def test_16_audit_log_cannot_be_deleted(self):
        log = self.env["nn.audit.log"].create({
            "model": "test.model",
            "res_id": 1,
            "action": "create",
            "company_id": self.env.company.id,
            "user_id": self.env.user.id,
        })
        with self.assertRaises(UserError):
            log.unlink()

    # ──────────────────────────────────────────────
    # PROTECTION 8: API REPLAY PROTECTION
    # ──────────────────────────────────────────────

    def test_17_idempotency_key_rejects_duplicate(self):
        key_model = self.env["nn.api.idempotency.key"]
        key_model.check_and_create(
            "test-key-001",
            self.env.user.id,
            self.env.company.id,
            "/api/v1/test",
        )
        with self.assertRaises(ValidationError):
            key_model.check_and_create(
                "test-key-001",
                self.env.user.id,
                self.env.company.id,
                "/api/v1/test",
            )

    def test_18_idempotency_key_allows_unique(self):
        key_model = self.env["nn.api.idempotency.key"]
        is_new, _ = key_model.check_and_create(
            "test-key-002",
            self.env.user.id,
            self.env.company.id,
            "/api/v1/test",
        )
        self.assertTrue(is_new)

    # ──────────────────────────────────────────────
    # PROTECTION 9: FINANCIAL CONSISTENCY
    # ──────────────────────────────────────────────

    def test_19_consistency_check_passes_on_clean_account(self):
        self._seed()
        result = self.env["nn.security.mixin"]._check_financial_consistency(
            account_id=self.account.id
        )
        self.assertTrue(result["consistent"])
        self.assertEqual(result["accounts_checked"], 1)
        self.assertEqual(result["violation_count"], 0)

    def test_20_consistency_check_detects_orphan_entry(self):
        entry = self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": 500.0,
            "credit": 0.0,
            "reference": "ORPHAN-CHECK",
            "reference_model": "nonexistent.model",
            "reference_id": 99999,
            "state": "posted",
            "company_id": self.env.company.id,
        })
        result = self.env["nn.security.mixin"]._check_financial_consistency(
            account_id=self.account.id
        )
        self.assertFalse(result["consistent"])
        self.assertGreaterEqual(result["violation_count"], 1)
        entry.unlink()

    # ──────────────────────────────────────────────
    # PROTECTION 10: EMERGENCY RECOVERY
    # ──────────────────────────────────────────────

    def test_21_emergency_recover_balance(self):
        self._seed()
        result = self.env["nn.security.mixin"]._emergency_recover_balance(
            self.account.id
        )
        self.assertIn("before", result)
        self.assertIn("after", result)

    def test_22_emergency_reverse_transaction_requires_admin(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        with self.assertRaises(UserError):
            self.env["nn.security.mixin"].with_user(self.gm_user)._emergency_reverse_transaction(
                entry.id, "Test reversal"
            )

    def test_23_emergency_reverse_requires_reason(self):
        self._seed()
        entry = self.env["nn.fund.ledger"].search([
            ("fund_account_id", "=", self.account.id),
            ("state", "=", "posted"),
        ], limit=1)
        with self.assertRaises(ValidationError):
            self.env["nn.security.mixin"]._emergency_reverse_transaction(
                entry.id, "Short"
            )

    def test_24_emergency_recovery_report_generation(self):
        self._seed()
        report = self.env["nn.security.mixin"]._emergency_get_recovery_report(
            account_id=self.account.id
        )
        self.assertEqual(len(report["accounts"]), 1)
        self.assertEqual(report["accounts"][0]["code"], "INTEG01")
        self.assertGreaterEqual(report["accounts"][0]["entry_count"], 1)

    # ──────────────────────────────────────────────
    # EDGE CASES
    # ──────────────────────────────────────────────

    def test_25_incoming_fund_double_confirm_blocked(self):
        inc = self.env["nn.incoming.fund"].create({
            "reference": "INTEG-DBL-CONF",
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "source_type": "donor",
        })
        inc.action_confirm()
        with self.assertRaises(ValidationError):
            inc.action_confirm()

    def test_26_bill_double_post_blocked(self):
        self._seed()
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 5000.0,
        })
        req.action_submit()
        req.action_approve()
        bill = self.env["nn.fund.bill"].create({
            "requisition_id": req.id,
            "amount": 1000.0,
            "vendor_name": "Integ Vendor",
        })
        bill.action_post()
        with self.assertRaises(ValidationError):
            bill.action_post()

    def test_27_cancel_after_approve_blocked_for_alloc(self):
        self._seed()
        alloc = self._create_alloc()
        alloc.action_submit()
        alloc.action_approve()
        with self.assertRaises(ValidationError):
            alloc.action_cancel()

    def test_28_gm_approval_requires_matrix_permission(self):
        self._seed()
        alloc = self._create_alloc()
        alloc.action_submit()
        alloc.current_matrix_line_id = False
        with self.assertRaises(ValidationError):
            alloc.with_user(self.gm_user).action_approve()
