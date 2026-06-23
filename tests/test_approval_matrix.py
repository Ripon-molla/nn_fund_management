from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("fund_management", "approval_matrix")
class TestApprovalMatrix(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})
        company = cls.env.company

        cls.Matrix = cls.env["nn.approval.matrix"]
        cls.MatrixLine = cls.env["nn.approval.matrix.line"]
        cls.Account = cls.env["nn.fund.account"]
        cls.Allocation = cls.env["nn.fund.allocation"]
        cls.Requisition = cls.env["nn.fund.requisition"]
        cls.Transfer = cls.env["nn.fund.transfer"]
        cls.Ledger = cls.env["nn.fund.ledger"]
        cls.Project = cls.env["nn.project"]
        cls.ExpenseHead = cls.env["nn.expense.head"]
        cls.ApprovalHistory = cls.env["nn.approval.history"]

        cls.GMGroup = cls.env.ref("nn_fund_management.group_gm_approver")
        cls.MDGroup = cls.env.ref("nn_fund_management.group_md_approver")
        cls.FinanceGroup = cls.env.ref("nn_fund_management.group_finance_user")
        cls.AdminGroup = cls.env.ref("nn_fund_management.group_fund_administrator")

        cls.gm_user = cls._create_user("matrix_gm", cls.GMGroup)
        cls.md_user = cls._create_user("matrix_md", cls.MDGroup)
        cls.finance_user = cls._create_user("matrix_finance", cls.FinanceGroup)
        cls.admin_user = cls._create_user("matrix_admin", cls.AdminGroup)
        cls.normal_user = cls._create_user("matrix_normal",
                                             cls.env.ref("base.group_user"))

        cls.fund_account = cls.Account.create({
            "name": "Matrix Test Fund",
            "code": "MTRX",
            "type": "main",
            "company_id": company.id,
        })

        cls.project = cls.Project.create({
            "name": "Matrix Test Project",
            "code": "MTRX-PRJ",
            "fund_account_id": cls.fund_account.id,
            "company_id": company.id,
        })

        cls.other_project = cls.Project.create({
            "name": "Other Matrix Project",
            "code": "MTRX-OTH",
            "fund_account_id": cls.fund_account.id,
            "company_id": company.id,
        })

        cls.expense_head = cls.ExpenseHead.create({
            "name": "Matrix Test EH",
            "code": "MTRX-EH",
            "project_id": cls.project.id,
            "company_id": company.id,
        })

        cls.Ledger.create({
            "date": fields.Datetime.now(),
            "reference": "MTRX-FUND-IN",
            "transaction_type": "incoming",
            "fund_account_id": cls.fund_account.id,
            "project_id": cls.project.id,
            "reference_model": "nn.incoming.fund",
            "reference_id": 9999,
            "debit": 500000.0,
            "credit": 0.0,
            "state": "posted",
            "company_id": company.id,
        })

    @classmethod
    def _create_user(cls, login, group):
        return cls.env["res.users"].create({
            "name": login.title(),
            "login": login,
            "password": login,
            "groups_id": [
                (4, cls.env.ref("base.group_user").id),
                (4, group.id),
            ],
        })

    def _create_matrix(self, request_type="nn.fund.allocation",
                        min_amount=0.0, max_amount=999999.0,
                        project_id=None, expense_head_id=None,
                        effective_date=None, expiration_date=None):
        return self.Matrix.create({
            "name": "Test Matrix",
            "request_type": request_type,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "company_id": self.env.company.id,
            "project_id": project_id,
            "expense_head_id": expense_head_id,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
        })

    def _create_line(self, matrix, sequence=10,
                     group_id=None, user_id=None):
        vals = {
            "matrix_id": matrix.id,
            "sequence": sequence,
        }
        if group_id:
            vals["approval_group_id"] = group_id
        elif user_id:
            vals["approval_user_id"] = user_id
        return self.MatrixLine.create(vals)

    # ── Matrix CRUD & Constraints ──

    def test_matrix_create(self):
        matrix = self._create_matrix()
        self.assertTrue(matrix.name)
        self.assertEqual(matrix.request_type, "nn.fund.allocation")
        self.assertEqual(matrix.min_amount, 0.0)
        self.assertEqual(matrix.max_amount, 999999.0)
        self.assertTrue(matrix.active)
        self.assertTrue(matrix.display_name)

    def test_matrix_display_name(self):
        matrix = self._create_matrix(name="Test Allocation Matrix",
                                      min_amount=1000.0, max_amount=50000.0)
        self.assertIn("Test Allocation Matrix", matrix.display_name)
        self.assertIn("1,000.00", matrix.display_name)
        self.assertIn("50,000.00", matrix.display_name)

    def test_matrix_amount_range_constraint(self):
        with self.assertRaises(ValidationError):
            self._create_matrix(min_amount=50000.0, max_amount=10000.0)

    def test_matrix_date_constraint(self):
        with self.assertRaises(ValidationError):
            self._create_matrix(
                effective_date=date.today(),
                expiration_date=date.today() - timedelta(days=1),
            )

    def test_matrix_line_unique_sequence(self):
        matrix = self._create_matrix()
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        with self.assertRaises(ValidationError):
            self._create_line(matrix, sequence=10, group_id=self.MDGroup.id)

    def test_matrix_line_group_or_user_required(self):
        matrix = self._create_matrix()
        with self.assertRaises(ValidationError):
            self.MatrixLine.create({
                "matrix_id": matrix.id,
                "sequence": 10,
            })

    def test_matrix_line_display_name_with_group(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self.assertIn("Step 10", line.display_name)
        self.assertIn(self.GMGroup.name, line.display_name)

    def test_matrix_line_display_name_with_user(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=20, user_id=self.admin_user.id)
        self.assertIn(self.admin_user.name, line.display_name)

    # ── _get_applicable_matrix ──

    def test_applicable_matrix_global_match(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0)
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertTrue(matrix)

    def test_applicable_matrix_no_match_out_of_range(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0)
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 100000.0, self.env.company.id
        )
        self.assertFalse(matrix)

    def test_applicable_matrix_wrong_request_type(self):
        self._create_matrix(request_type="nn.fund.allocation")
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.requisition", 10000.0, self.env.company.id
        )
        self.assertFalse(matrix)

    def test_applicable_matrix_project_scope(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0,
                              project_id=self.project.id)
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id,
            project_id=self.project.id
        )
        self.assertTrue(matrix)

    def test_applicable_matrix_project_scope_preferred_over_global(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0)
        project_matrix = self._create_matrix(
            min_amount=0.0, max_amount=50000.0,
            project_id=self.project.id
        )
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id,
            project_id=self.project.id
        )
        self.assertEqual(matrix.id, project_matrix.id)

    def test_applicable_matrix_expense_head_scope(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0,
                              expense_head_id=self.expense_head.id)
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id,
            expense_head_id=self.expense_head.id
        )
        self.assertTrue(matrix)

    def test_applicable_matrix_project_expense_exact_match(self):
        self._create_matrix(min_amount=0.0, max_amount=50000.0)
        exact = self._create_matrix(
            min_amount=0.0, max_amount=50000.0,
            project_id=self.project.id,
            expense_head_id=self.expense_head.id
        )
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id,
            project_id=self.project.id,
            expense_head_id=self.expense_head.id
        )
        self.assertEqual(matrix.id, exact.id)

    # ── Effective / Expiration Dates ──

    def test_applicable_matrix_future_effective_date(self):
        self._create_matrix(
            min_amount=0.0, max_amount=50000.0,
            effective_date=date.today() + timedelta(days=30),
        )
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertFalse(matrix)

    def test_applicable_matrix_past_expiration_date(self):
        self._create_matrix(
            min_amount=0.0, max_amount=50000.0,
            expiration_date=date.today() - timedelta(days=1),
        )
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertFalse(matrix)

    def test_applicable_matrix_within_date_range(self):
        self._create_matrix(
            min_amount=0.0, max_amount=50000.0,
            effective_date=date.today() - timedelta(days=10),
            expiration_date=date.today() + timedelta(days=10),
        )
        matrix = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertTrue(matrix)

    def test_applicable_matrix_inactive_excluded(self):
        matrix = self._create_matrix(min_amount=0.0, max_amount=50000.0)
        matrix.active = False
        result = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertFalse(result)

    # ── _get_valid_lines ──

    def test_get_valid_lines_empty_matrix(self):
        lines = self.Matrix._get_valid_lines(self.Matrix)
        self.assertEqual(len(lines), 0)

    def test_get_valid_lines_returns_sorted(self):
        matrix = self._create_matrix(min_amount=0.0, max_amount=50000.0)
        line3 = self._create_line(matrix, sequence=30, group_id=self.MDGroup.id)
        line1 = self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        line2 = self._create_line(matrix, sequence=20, group_id=self.FinanceGroup.id)
        lines = self.Matrix._get_valid_lines(matrix)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].id, line1.id)
        self.assertEqual(lines[1].id, line2.id)
        self.assertEqual(lines[2].id, line3.id)

    def test_get_valid_lines_excludes_inactive(self):
        matrix = self._create_matrix(min_amount=0.0, max_amount=50000.0)
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        inactive = self._create_line(matrix, sequence=20, group_id=self.MDGroup.id)
        inactive.active = False
        lines = self.Matrix._get_valid_lines(matrix)
        self.assertEqual(len(lines), 1)

    # ── _get_approvers / _user_can_approve ──

    def test_line_get_approvers_by_group(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        approvers = line._get_approvers()
        self.assertIn(self.gm_user, approvers)
        self.assertNotIn(self.md_user, approvers)

    def test_line_get_approvers_by_user(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=10, user_id=self.admin_user.id)
        approvers = line._get_approvers()
        self.assertEqual(approvers.id, self.admin_user.id)

    def test_line_user_can_approve_group_match(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self.assertTrue(line.with_user(self.gm_user)._user_can_approve())
        self.assertFalse(line.with_user(self.md_user)._user_can_approve())

    def test_line_user_can_approve_user_match(self):
        matrix = self._create_matrix()
        line = self._create_line(matrix, sequence=10, user_id=self.admin_user.id)
        self.assertTrue(line.with_user(self.admin_user)._user_can_approve())
        self.assertFalse(line.with_user(self.gm_user)._user_can_approve())

    # ── action_test_matrix ──

    def test_action_test_matrix_valid(self):
        matrix = self._create_matrix()
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self._create_line(matrix, sequence=20, group_id=self.MDGroup.id)
        self.assertTrue(matrix.action_test_matrix())

    def test_action_test_matrix_no_lines(self):
        matrix = self._create_matrix()
        with self.assertRaises(ValueError):
            matrix.action_test_matrix()

    def test_action_test_matrix_line_no_group_no_user(self):
        matrix = self._create_matrix()
        with self.assertRaises(ValueError):
            self.MatrixLine.create({
                "matrix_id": matrix.id,
                "sequence": 10,
            })

    # ── End-to-End: Allocation with Custom Matrix ──

    def test_allocation_with_matrix_single_step(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 25000.0,
            "purpose": "Matrix test allocation",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "pending_approval")
        self.assertTrue(alloc.current_matrix_line_id)

        alloc.with_user(self.gm_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    def test_allocation_with_matrix_multi_step(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=100000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self._create_line(matrix, sequence=20, group_id=self.MDGroup.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 75000.0,
            "purpose": "Multi-step matrix test",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "pending_approval")
        step1 = alloc.current_matrix_line_id
        self.assertEqual(step1.sequence, 10)

        alloc.with_user(self.gm_user).action_approve()
        self.assertEqual(alloc.state, "pending_approval")
        step2 = alloc.current_matrix_line_id
        self.assertEqual(step2.sequence, 20)

        alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    def test_allocation_with_user_specific_approver(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, user_id=self.admin_user.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 15000.0,
            "purpose": "User-specific approver test",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "pending_approval")

        with self.assertRaises(ValidationError):
            alloc.with_user(self.gm_user).action_approve()

        alloc.with_user(self.admin_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    def test_allocation_reject_by_non_approver_blocked(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 10000.0,
            "purpose": "Non-approver reject test",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "pending_approval")

        with self.assertRaises(ValidationError):
            alloc.with_user(self.finance_user).action_approve()

    def test_allocation_with_three_step_matrix(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=200000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self._create_line(matrix, sequence=20, group_id=self.FinanceGroup.id)
        self._create_line(matrix, sequence=30, group_id=self.MDGroup.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 150000.0,
            "purpose": "Three-step approval",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        self.assertEqual(alloc.state, "pending_approval")

        alloc.with_user(self.gm_user).action_approve()
        self.assertEqual(alloc.state, "pending_approval")

        alloc.with_user(self.finance_user).action_approve()
        self.assertEqual(alloc.state, "pending_approval")

        alloc.with_user(self.md_user).action_approve()
        self.assertEqual(alloc.state, "approved")

    # ── Requisition with Matrix ──

    def test_requisition_with_matrix(self):
        matrix = self._create_matrix(
            request_type="nn.fund.requisition",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)

        req = self.Requisition.create({
            "project_id": self.project.id,
            "amount": 20000.0,
            "company_id": self.env.company.id,
        })
        req.action_submit()
        self.assertEqual(req.state, "pending_approval")
        req.with_user(self.gm_user).action_approve()
        self.assertEqual(req.state, "approved")

    def test_requisition_matrix_higher_amount_multi_step(self):
        matrix = self._create_matrix(
            request_type="nn.fund.requisition",
            min_amount=50000.01, max_amount=200000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)
        self._create_line(matrix, sequence=20, group_id=self.MDGroup.id)

        req = self.Requisition.create({
            "project_id": self.project.id,
            "amount": 100000.0,
            "company_id": self.env.company.id,
        })
        req.action_submit()
        self.assertEqual(req.state, "pending_approval")
        req.with_user(self.gm_user).action_approve()
        self.assertEqual(req.state, "pending_approval")
        req.with_user(self.md_user).action_approve()
        self.assertEqual(req.state, "approved")

    # ── Transfer with Matrix ──

    def test_transfer_with_matrix(self):
        matrix = self._create_matrix(
            request_type="nn.fund.transfer",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)

        trf = self.Transfer.create({
            "source_project_id": self.project.id,
            "destination_project_id": self.other_project.id,
            "amount": 30000.0,
            "reason": "Matrix test transfer",
            "company_id": self.env.company.id,
        })
        trf.action_submit()
        self.assertEqual(trf.state, "pending_approval")
        trf.with_user(self.gm_user).action_approve()
        self.assertEqual(trf.state, "approved")
        self.assertTrue(trf.source_ledger_entry_id)
        self.assertTrue(trf.destination_ledger_entry_id)

    # ── Backward Compatibility ──

    def test_fallback_to_old_rule(self):
        result = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        self.assertTrue(result)
        self.assertEqual(result._name, "nn.approval.rule")
        self.assertEqual(result.name, "Allocation - Low Value")

    def test_fallback_rule_lines_work_as_matrix_lines(self):
        rule = self.Matrix._get_applicable_matrix(
            "nn.fund.allocation", 25000.0, self.env.company.id
        )
        lines = self.Matrix._get_valid_lines(rule)
        self.assertTrue(lines)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0]._get_approvers())
        self.assertTrue(
            lines[0].with_user(self.gm_user)._user_can_approve()
        )

    # ── Approval History Records Matrix Line ──

    def test_approval_history_records_matrix_line(self):
        matrix = self._create_matrix(
            request_type="nn.fund.allocation",
            min_amount=0.0, max_amount=50000.0,
        )
        self._create_line(matrix, sequence=10, group_id=self.GMGroup.id)

        alloc = self.Allocation.create({
            "fund_account_id": self.fund_account.id,
            "project_id": self.project.id,
            "amount": 10000.0,
            "purpose": "History matrix test",
            "request_date": fields.Date.today(),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })
        alloc.action_submit()
        alloc.with_user(self.gm_user).action_approve()

        history = self.ApprovalHistory.search([
            ("request_type", "=", "nn.fund.allocation"),
            ("request_id", "=", alloc.id),
        ])
        self.assertTrue(history)
        self.assertTrue(history[-1].matrix_line_id)
        self.assertEqual(
            history[-1].matrix_line_id.sequence, 10
        )
