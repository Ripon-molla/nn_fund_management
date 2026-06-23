from datetime import date

from odoo import api, fields, models, _


class ApprovalMatrix(models.Model):
    """Dynamic Approval Matrix — configurable unlimited-level approval engine.

    Replaces the old hardcoded GM/MD approval logic with a flexible matrix
    that supports unlimited approval levels, project/expense head scoping,
    effective/expiration dates, and user-specific assignments.

    Key capabilities:
    - Unlimited approval levels (GM, Finance, MD, Board, etc.)
    - Per-request-type, per-company, per-project, per-expense-head rules
    - Amount-based tier selection (0-50k, 50k-200k, etc.)
    - Effective date / expiration date for time-bounded rules
    - Group-based and user-based approval steps
    - Sequence validation prevents skipped levels

    To add a new approval level: Create a new matrix line with the
    desired group. No code changes needed.
    """

    _name = "nn.approval.matrix"
    _description = "Approval Matrix"
    _order = "request_type, min_amount, name"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    name = fields.Char(
        string="Rule Name",
        required=True,
        tracking=True,
    )

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    request_type = fields.Selection(
        selection=[
            ("nn.fund.allocation", "Fund Allocation"),
            ("nn.fund.requisition", "Fund Requisition"),
            ("nn.fund.transfer", "Fund Transfer"),
        ],
        string="Request Type",
        required=True,
        tracking=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project Scope",
        tracking=True,
        check_company=True,
        help="Leave empty to apply to all projects.",
    )

    expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Expense Head Scope",
        tracking=True,
        check_company=True,
        help="Leave empty to apply to all expense heads.",
    )

    min_amount = fields.Monetary(
        string="Minimum Amount",
        required=True,
        default=0.0,
        currency_field="currency_id",
        tracking=True,
    )

    max_amount = fields.Monetary(
        string="Maximum Amount",
        required=True,
        default=0.0,
        currency_field="currency_id",
        tracking=True,
    )

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
    )

    effective_date = fields.Date(
        string="Effective Date",
        tracking=True,
        help="Date from which this matrix becomes active. "
             "Leave empty for immediate effect.",
    )

    expiration_date = fields.Date(
        string="Expiration Date",
        tracking=True,
        help="Date after which this matrix expires. "
             "Leave empty for no expiration.",
    )

    line_ids = fields.One2many(
        comodel_name="nn.approval.matrix.line",
        inverse_name="matrix_id",
        string="Approval Lines",
        copy=True,
    )

    _sql_constraints = [
        (
            "check_amount_range",
            "CHECK(max_amount >= min_amount)",
            "Maximum amount must be >= minimum amount.",
        ),
        (
            "check_dates",
            "CHECK(expiration_date IS NULL OR effective_date IS NULL OR expiration_date >= effective_date)",
            "Expiration date must be after effective date.",
        ),
    ]

    @api.depends("name", "request_type", "min_amount", "max_amount")
    def _compute_display_name(self):
        for record in self:
            record.display_name = (
                f"{record.name} "
                f"({record.min_amount:,.2f} - {record.max_amount:,.2f})"
            )

    @api.model
    def _get_applicable_matrix(self, request_type, amount, company_id,
                                project_id=None, expense_head_id=None):
        """Find the best matching matrix for the given criteria.

        Search order:
        1. Exact match: project + expense head scoped
        2. Project-scoped only
        3. Expense head-scoped only
        4. Global (no project/expense head scope)
        5. Fallback to old approval rule for backward compatibility
        """
        today = date.today()
        domain = [
            ("request_type", "=", request_type),
            ("min_amount", "<=", amount),
            ("max_amount", ">=", amount),
            ("active", "=", True),
            ("company_id", "=", company_id),
            "|",
            ("effective_date", "<=", today),
            ("effective_date", "=", False),
            "|",
            ("expiration_date", ">=", today),
            ("expiration_date", "=", False),
        ]

        # Try exact project + expense head match first
        if project_id and expense_head_id:
            matrix = self.search(
                domain + [
                    ("project_id", "=", project_id),
                    ("expense_head_id", "=", expense_head_id),
                ],
                limit=1,
            )
            if matrix:
                return matrix

        # Try project-only match
        if project_id:
            matrix = self.search(
                domain + [
                    ("project_id", "=", project_id),
                    ("expense_head_id", "=", False),
                ],
                limit=1,
            )
            if matrix:
                return matrix

        # Try expense-head-only match
        if expense_head_id:
            matrix = self.search(
                domain + [
                    ("project_id", "=", False),
                    ("expense_head_id", "=", expense_head_id),
                ],
                limit=1,
            )
            if matrix:
                return matrix

        # Global match (no scope)
        matrix = self.search(
            domain + [
                ("project_id", "=", False),
                ("expense_head_id", "=", False),
            ],
            limit=1,
        )
        if matrix:
            return matrix

        # Try new configurable approval rules
        matching_lines = self.env["nn.approval.rule.line"].search([
            ("rule_id.request_type", "=", request_type),
            ("rule_id.company_id", "=", company_id),
            ("rule_id.active", "=", True),
            ("active", "=", True),
            ("minimum_amount", "<=", amount),
            ("maximum_amount", ">=", amount),
        ], limit=1)
        if matching_lines:
            return matching_lines.rule_id

        # Fallback: old approval rule (backward compatibility)
        return self.env["nn.approval.rule"]._get_applicable_rule(
            request_type, amount, company_id
        )

    @api.model
    def _get_valid_lines(self, matrix, amount=0.0):
        """Get valid (non-expired, effective) approval lines from matrix.

        For new-style nn.approval.rule lines, filters by amount range.
        """
        if not matrix:
            return self.env["nn.approval.matrix.line"]
        if hasattr(matrix, "line_ids"):
            return matrix.line_ids.filtered("active").sorted("sequence")
        if hasattr(matrix, "rule_line_ids"):
            return matrix.rule_line_ids.filtered(
                lambda l: l.active and l.minimum_amount <= amount <= l.maximum_amount
            ).sorted("sequence")
        if hasattr(matrix, "step_ids"):
            return matrix.step_ids.sorted("sequence")
        return self.env["nn.approval.matrix.line"]

    def action_test_matrix(self):
        """Test this matrix configuration for validity."""
        self.ensure_one()
        if not self.line_ids:
            raise ValueError(_("Matrix has no approval lines defined."))
        lines = self.line_ids.filtered("active").sorted("sequence")
        if not lines:
            raise ValueError(_("No active approval lines in this matrix."))
        for line in lines:
            if not line.approval_group_id and not line.approval_user_id:
                raise ValueError(
                    _("Line %d has no group or user assigned.") % line.sequence
                )
        return True


class ApprovalMatrixLine(models.Model):
    """A single approval step within an approval matrix.

    Unlimited levels are supported. Each line represents one step
    in the approval chain. Steps are processed in sequence order.

    Examples:
    Sequence 10: GM Group
    Sequence 20: Finance Group
    Sequence 30: MD Group
    Sequence 40: Board Group
    """

    _name = "nn.approval.matrix.line"
    _description = "Approval Matrix Line"
    _order = "matrix_id, sequence"
    _rec_name = "display_name"
    _check_company_auto = True

    matrix_id = fields.Many2one(
        comodel_name="nn.approval.matrix",
        string="Approval Matrix",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sequence = fields.Integer(
        string="Sequence",
        required=True,
        default=10,
    )

    display_name = fields.Char(
        string="Step Name",
        compute="_compute_display_name",
        store=True,
    )

    approval_group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Approval Group",
        domain=[("name", "not ilike", "base.")],
        help="Group whose members can approve at this step. "
             "Set up custom groups via Settings > Users & Companies > Groups.",
    )

    approval_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Specific Approver",
        domain=[("share", "=", False)],
        help="Specific user who must approve at this step. "
             "If set, overrides the group-based approval.",
    )

    approval_type = fields.Selection(
        selection=[
            ("group", "Group-based approval"),
            ("user", "User-specific approval"),
        ],
        string="Approval Type",
        required=True,
        default="group",
        compute="_compute_approval_type",
        store=True,
        readonly=False,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="matrix_id.company_id",
        store=True,
        index=True,
    )

    _sql_constraints = [
        (
            "check_group_or_user_required",
            "CHECK(approval_group_id IS NOT NULL OR approval_user_id IS NOT NULL)",
            "Each approval line must have either a group or a specific user assigned.",
        ),
        (
            "unique_sequence_per_matrix",
            "UNIQUE(matrix_id, sequence)",
            "Sequence must be unique per approval matrix.",
        ),
    ]

    @api.depends("approval_group_id", "approval_user_id", "sequence")
    def _compute_display_name(self):
        for record in self:
            if record.approval_group_id:
                record.display_name = (
                    f"Step {record.sequence}: {record.approval_group_id.name}"
                )
            elif record.approval_user_id:
                record.display_name = (
                    f"Step {record.sequence}: {record.approval_user_id.name}"
                )
            else:
                record.display_name = f"Step {record.sequence}: (unassigned)"

    @api.depends("approval_group_id", "approval_user_id")
    def _compute_approval_type(self):
        for record in self:
            if record.approval_user_id:
                record.approval_type = "user"
            else:
                record.approval_type = "group"

    def _get_approvers(self):
        """Return the res.users who can approve at this step."""
        self.ensure_one()
        if self.approval_user_id:
            return self.approval_user_id
        if self.approval_group_id:
            return self.approval_group_id.users
        return self.env["res.users"]

    def _user_can_approve(self, user=None):
        """Check if a user can approve at this step."""
        self.ensure_one()
        user = user or self.env.user
        if self.approval_user_id:
            return user.id == self.approval_user_id.id
        if self.approval_group_id:
            return self.approval_group_id.id in user.groups_id.ids
        return False
