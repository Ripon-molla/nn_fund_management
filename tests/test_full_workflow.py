from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "fund_management", "workflow")
class TestFullWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.group_gm = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.group_finance = cls.env.ref("nn_fund_management.group_finance_user")
        cls.group_md = cls.env.ref("nn_fund_management.group_md_approver")
        cls.gm_user = cls.env["res.users"].create({
            "name": "GM WF",
            "login": "gm_wf",
            "password": "gm_wf",
            "groups_id": [(6, 0, [cls.group_gm.id])],
        })
        cls.finance_user = cls.env["res.users"].create({
            "name": "Fin WF",
            "login": "fin_wf",
            "password": "fin_wf",
            "groups_id": [(6, 0, [cls.group_finance.id])],
        })
        cls.md_user = cls.env["res.users"].create({
            "name": "MD WF",
            "login": "md_wf",
            "password": "md_wf",
            "groups_id": [(6, 0, [cls.group_md.id])],
        })
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "WF Main Account",
            "code": "WFM001",
            "currency_id": cls.currency.id,
        })
        cls.project = cls.env["nn.project"].create({
            "name": "WF Project",
            "code": "WFPRJ",
            "fund_account_id": cls.account.id,
        })

    def _seed(self, amount=1000000.0):
        self.env["nn.fund.ledger"].create({
            "fund_account_id": self.account.id,
            "transaction_type": "incoming",
            "debit": amount,
            "credit": 0.0,
            "reference": "WF-SEED",
            "state": "posted",
            "company_id": self.env.company.id,
        })
        self.account.invalidate_recordset()

    # ── Full lifecycle: incoming → allocate → transfer → requisition → bill → close ──
    def test_01_full_lifecycle(self):
        self._seed()
        # Create direct incoming fund
        inc = self.env["nn.incoming.fund"].create({
            "reference": "WF-INC-001",
            "fund_account_id": self.account.id,
            "amount": 500000.0,
            "source_type": "donor",
        })
        inc.action_confirm()
        self.assertEqual(inc.state, "confirmed")
        self.account.invalidate_recordset()
        # Allocate 300k
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 300000.0,
            "purpose": "WF allocation",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "submitted")
        alloc.action_approve()
        self.assertEqual(alloc.state, "approved")
        # Transfer 100k
        dest_account = self.env["nn.fund.account"].create({
            "name": "WF Dest",
            "code": "WFDST",
            "currency_id": self.currency.id,
        })
        dest_project = self.env["nn.project"].create({
            "name": "WF Dest Proj",
            "code": "WFDPRJ",
            "fund_account_id": dest_account.id,
        })
        trf = self.env["nn.fund.transfer"].create({
            "source_project_id": self.project.id,
            "destination_project_id": dest_project.id,
            "amount": 100000.0,
            "reason": "WF transfer",
        })
        trf.action_submit()
        trf.action_approve()
        self.assertEqual(trf.state, "approved")
        self.account.invalidate_recordset()
        dest_account.invalidate_recordset()
        # Requisition 150k
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 150000.0,
        })
        req.action_submit()
        req.action_approve()
        self.assertEqual(req.state, "approved")
        self.assertEqual(req.remaining_billable_amount, 150000.0)
        # Bill 100k
        bill = self.env["nn.fund.bill"].create({
            "requisition_id": req.id,
            "amount": 100000.0,
            "vendor_name": "WF Vendor",
        })
        bill.action_post()
        self.assertEqual(bill.state, "posted")
        req.invalidate_recordset()
        self.assertEqual(req.remaining_billable_amount, 50000.0)
        # Close requisition
        req.action_close()
        self.assertEqual(req.state, "closed")
        self.account.invalidate_recordset()

    # ── Multi-step approval via 3-step matrix ──
    def test_02_three_step_approval_workflow(self):
        self._seed()
        matrix = self.env["nn.approval.matrix"].create({
            "name": "WF 3-Step Matrix",
            "request_type": "nn.fund.allocation",
            "min_amount": 0.0,
            "max_amount": 9999999.0,
            "company_id": self.env.company.id,
        })
        self.env["nn.approval.matrix.line"].create({
            "matrix_id": matrix.id,
            "sequence": 10,
            "approval_group_id": self.group_gm.id,
            "name": "GM",
        })
        self.env["nn.approval.matrix.line"].create({
            "matrix_id": matrix.id,
            "sequence": 20,
            "approval_group_id": self.group_finance.id,
            "name": "Finance",
        })
        self.env["nn.approval.matrix.line"].create({
            "matrix_id": matrix.id,
            "sequence": 30,
            "approval_group_id": self.group_md.id,
            "name": "MD",
        })
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 50000.0,
            "purpose": "3-Step test",
            "project_id": self.project.id,
        })
        alloc.with_user(self.gm_user).action_submit()
        self.assertEqual(alloc.state, "pending_approval")
        alloc.with_user(self.gm_user).action_approve()
        alloc.with_user(self.finance_user).action_approve()
        alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    # ── Audit log created for every step ──
    def test_03_audit_log_for_every_step(self):
        self._seed()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 10000.0,
            "purpose": "Audit trail test",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        alloc.action_approve()
        logs = self.env["nn.audit.log"].search([
            ("model", "=", "nn.fund.allocation"),
            ("res_id", "=", alloc.id),
        ])
        self.assertGreaterEqual(len(logs), 2)

    # ── Company isolation: different company cannot see records ──
    def test_04_company_isolation(self):
        self._seed()
        other_company = self.env["res.company"].create({"name": "WF Other Co"})
        self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "purpose": "Isolation test",
            "project_id": self.project.id,
        })
        count_default = self.env["nn.fund.allocation"].search_count([])
        other_env = self.env["nn.fund.allocation"].with_context(force_company=other_company.id)
        count_other = other_env.search_count([])
        self.assertGreater(count_default, count_other)

    # ── Overbilling blocked at model level ──
    def test_05_overbilling_blocked(self):
        self._seed()
        req = self.env["nn.fund.requisition"].create({
            "project_id": self.project.id,
            "amount": 10000.0,
        })
        req.action_submit()
        req.action_approve()
        bill = self.env["nn.fund.bill"].create({
            "requisition_id": req.id,
            "amount": 15000.0,
            "vendor_name": "Overbill Test",
        })
        with self.assertRaises(ValidationError):
            bill.action_post()

    # ── Transfer between same accounts blocked ──
    def test_06_same_account_transfer_blocked(self):
        dest_project = self.env["nn.project"].create({
            "name": "Same Acc Proj",
            "code": "SAMEACC",
            "fund_account_id": self.account.id,
        })
        with self.assertRaises(ValidationError):
            self.env["nn.fund.transfer"].create({
                "source_project_id": self.project.id,
                "destination_project_id": dest_project.id,
                "amount": 5000.0,
                "reason": "Same account test",
            })

    # ── Cancel then reallocate works ──
    def test_07_cancel_reallocate(self):
        self._seed()
        alloc = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "purpose": "Cancel/Reallocate",
            "project_id": self.project.id,
        })
        alloc.action_submit()
        alloc.action_cancel()
        self.account.invalidate_recordset()
        alloc2 = self.env["nn.fund.allocation"].create({
            "fund_account_id": self.account.id,
            "amount": 5000.0,
            "purpose": "Reallocated",
            "project_id": self.project.id,
        })
        alloc2.action_submit()
        self.assertEqual(alloc2.state, "submitted")
