from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "fund_management", "approval_rule")
class TestApprovalRuleExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.group_gm = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.group_md = cls.env.ref("nn_fund_management.group_md_approver")

    # ── nn.approval.rule _compute_display_name ──
    def test_01_rule_display_name(self):
        rule = self.env["nn.approval.rule"].create({
            "name": "Test Rule",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 50000.0,
        })
        self.assertIn("Test Rule", rule.display_name)

    # ── SQL constraint: max_amount >= min_amount ──
    def test_02_rule_amount_range_constraint(self):
        with self.assertRaises(Exception):
            self.env["nn.approval.rule"].create({
                "name": "Bad Range",
                "request_type": "nn.fund.allocation",
                "min_amount": 50000.0,
                "max_amount": 10000.0,
            })

    # ── SQL constraint: unique_sequence_per_rule ──
    def test_03_step_unique_sequence(self):
        rule = self.env["nn.approval.rule"].create({
            "name": "Seq Constraint",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 100000.0,
        })
        self.env["nn.approval.step"].create({
            "rule_id": rule.id,
            "sequence": 10,
            "approver_type": "gm",
            "approver_group_id": self.group_gm.id,
        })
        with self.assertRaises(Exception):
            self.env["nn.approval.step"].create({
                "rule_id": rule.id,
                "sequence": 10,
                "approver_type": "md",
                "approver_group_id": self.group_md.id,
            })

    # ── _get_applicable_rule returns correct rule ──
    def test_04_get_applicable_rule(self):
        rule = self.env["nn.approval.rule"].create({
            "name": "Applicable Test",
            "request_type": "nn.fund.allocation",
            "min_amount": 1000.0,
            "max_amount": 50000.0,
        })
        result = self.env["nn.approval.rule"]._get_applicable_rule(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertEqual(result.id, rule.id)

    def test_05_get_applicable_rule_out_of_range(self):
        self.env["nn.approval.rule"].create({
            "name": "Low Range",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 50000.0,
        })
        result = self.env["nn.approval.rule"]._get_applicable_rule(
            "nn.fund.allocation", 100000.0, self.env.company.id
        )
        self.assertFalse(result)
