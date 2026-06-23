from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, ValidationError


@tagged("post_install", "-at_install", "fund_management", "security")
class TestSecurityMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.group_admin = cls.env.ref("nn_fund_management.group_fund_administrator")
        cls.group_finance = cls.env.ref("nn_fund_management.group_finance_user")
        cls.group_gm = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.group_user = cls.env.ref("nn_fund_management.group_fund_user")
        cls.admin = cls.env.ref("base.user_admin")
        cls.finance_user = cls.env["res.users"].create({
            "name": "Finance Tester",
            "login": "fin_tester",
            "password": "fin_tester",
            "groups_id": [(6, 0, [cls.group_finance.id])],
        })
        cls.gm_user = cls.env["res.users"].create({
            "name": "GM Tester",
            "login": "gm_tester",
            "password": "gm_tester",
            "groups_id": [(6, 0, [cls.group_gm.id])],
        })
        cls.base_user = cls.env["res.users"].create({
            "name": "Base Tester",
            "login": "base_tester",
            "password": "base_tester",
        })
        cls.currency = cls.env.ref("base.USD")
        cls.other_company = cls.env["res.company"].create({
            "name": "Other Company",
        })
        cls.account = cls.env["nn.fund.account"].create({
            "name": "Security Test Account",
            "code": "SEC001",
            "currency_id": cls.currency.id,
        })
        cls.mixin = cls.env["nn.security.mixin"]

    # ── _check_company_permission ──
    def test_01_check_company_permission_same_company(self):
        rec = self.env["nn.fund.account"].browse(self.account.id)
        result = self.mixin._check_company_permission(rec)
        self.assertTrue(result)

    def test_02_check_company_permission_cross_company(self):
        other_account = self.env["nn.fund.account"].with_context(
            force_company=self.other_company.id
        ).create({
            "name": "Other Account",
            "code": "OTH001",
            "currency_id": self.currency.id,
            "company_id": self.other_company.id,
        })
        with self.assertRaises(AccessError):
            self.mixin._check_company_permission(other_account)

    # ── _check_state_transition ──
    def test_03_check_state_transition_allowed(self):
        result = self.mixin._check_state_transition("draft", ["draft", "submitted"], "submit")
        self.assertTrue(result)

    def test_04_check_state_transition_blocked(self):
        with self.assertRaises(ValidationError):
            self.mixin._check_state_transition("approved", ["draft", "submitted"], "submit")

    # ── _check_write_permission ──
    def test_05_check_write_permission_admin(self):
        rec = self.account.with_user(self.admin)
        result = rec._check_write_permission()
        self.assertTrue(result)

    def test_06_check_write_permission_no_access(self):
        no_access_user = self.env["res.users"].create({
            "name": "No Access",
            "login": "no_access",
            "password": "no_access",
        })
        rec = self.account.with_user(no_access_user)
        with self.assertRaises(AccessError):
            rec._check_write_permission()

    # ── _check_unlink_permission ──
    def test_07_check_unlink_permission_admin(self):
        temp = self.env["nn.fund.account"].create({
            "name": "Temp",
            "code": "TMP001",
            "currency_id": self.currency.id,
        })
        result = temp.with_user(self.admin)._check_unlink_permission()
        self.assertTrue(result)

    def test_08_check_unlink_permission_no_access(self):
        no_access_user = self.env["res.users"].create({
            "name": "No Unlink",
            "login": "no_unlink",
            "password": "no_unlink",
        })
        temp = self.env["nn.fund.account"].create({
            "name": "Temp2",
            "code": "TMP002",
            "currency_id": self.currency.id,
        })
        with self.assertRaises(AccessError):
            temp.with_user(no_access_user)._check_unlink_permission()

    # ── _check_duplicate_field ──
    def test_09_check_duplicate_field_found(self):
        self.env["nn.fund.account"].create({
            "name": "Dup Check",
            "code": "DUP001",
            "currency_id": self.currency.id,
        })
        result = self.mixin._check_duplicate_field("code", "DUP001")
        self.assertTrue(result)

    def test_10_check_duplicate_field_not_found(self):
        result = self.mixin._check_duplicate_field("code", "NONEXISTENT")
        self.assertFalse(result)

    def test_11_check_duplicate_field_exclude_self(self):
        acc = self.env["nn.fund.account"].create({
            "name": "Self Exclude",
            "code": "SELF001",
            "currency_id": self.currency.id,
        })
        result = self.mixin._check_duplicate_field("code", "SELF001", exclude_id=acc.id)
        self.assertFalse(result)

    # ── _check_duplicate_transaction ──
    def test_12_check_duplicate_transaction(self):
        ref = "TXN-UNIQUE-001"
        result = self.mixin._check_duplicate_transaction(ref, self.env.company.id)
        self.assertFalse(result)

    # ── _validate_positive_amount ──
    def test_13_validate_positive_amount_valid(self):
        result = self.mixin._validate_positive_amount(100.0)
        self.assertTrue(result)

    def test_14_validate_positive_amount_zero(self):
        with self.assertRaises(ValidationError):
            self.mixin._validate_positive_amount(0.0)

    def test_15_validate_positive_amount_negative(self):
        with self.assertRaises(ValidationError):
            self.mixin._validate_positive_amount(-50.0)

    # ── _check_user_is_approver ──
    def test_16_check_user_is_approver_matches(self):
        result = self.gm_user._check_user_is_approver("nn_fund_management.group_gm_approver")
        self.assertTrue(result)

    def test_17_check_user_is_approver_no_match(self):
        with self.assertRaises(AccessError):
            self.base_user._check_user_is_approver("nn_fund_management.group_gm_approver")

    # ── _check_approval_sequence ──
    def test_18_check_approval_sequence_first_step(self):
        rule = self.env["nn.approval.rule"].create({
            "name": "Seq Test",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 1000.0,
        })
        step1 = self.env["nn.approval.step"].create({
            "rule_id": rule.id,
            "sequence": 10,
            "approver_type": "gm",
            "approver_group_id": self.group_gm.id,
        })
        alloc = self.env["nn.fund.allocation"].create({
            "amount": 500.0,
            "fund_account_id": self.account.id,
            "project_id": False,
            "expense_head_id": False,
            "purpose": "Sequence test",
        })
        result = alloc._check_approval_sequence(rule, step1)
        self.assertTrue(result)

    # ── _enforce_same_company ──
    def test_19_enforce_same_company_all_same(self):
        acc2 = self.env["nn.fund.account"].create({
            "name": "Same Co",
            "code": "SAME01",
            "currency_id": self.currency.id,
        })
        result = self.mixin._enforce_same_company(self.account + acc2)
        self.assertTrue(result)

    def test_20_enforce_same_company_mixed(self):
        acc_other = self.env["nn.fund.account"].create({
            "name": "Other Co",
            "code": "OTH002",
            "currency_id": self.currency.id,
            "company_id": self.other_company.id,
        })
        with self.assertRaises(ValidationError):
            self.mixin._enforce_same_company(self.account + acc_other)

    # ── _enforce_multi_company_consistency ──
    def test_21_enforce_multi_company_consistency_valid(self):
        result = self.mixin._enforce_multi_company_consistency(self.env.company.id, "incoming")
        self.assertTrue(result)

    def test_22_enforce_multi_company_consistency_no_company(self):
        with self.assertRaises(ValidationError):
            self.mixin._enforce_multi_company_consistency(False, "incoming")

    # ── _check_reconciliation_health (happy path) ──
    def test_23_check_reconciliation_health_no_reconciliation(self):
        result = self.mixin._check_reconciliation_health()
        self.assertTrue(result)

    def test_24_check_reconciliation_health_after_ok_reconciliation(self):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": 1000.0,
            "credit": 0.0,
            "reference": "HEALTH_OK",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        rec = self.env["nn.ledger.reconciliation"].create({
            "date": self.env["nn.ledger.reconciliation"]._fields["date"].default(self.env["nn.ledger.reconciliation"]),
            "company_id": self.env.company.id,
        })
        rec.action_run_reconciliation()
        result = self.mixin._check_reconciliation_health()
        self.assertTrue(result)
