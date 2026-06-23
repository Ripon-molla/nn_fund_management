from odoo import api, fields, models, _


class ApprovalRule(models.Model):
    _name = "nn.approval.rule"
    _description = "Approval Rule"
    _order = "request_type, name"
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

    rule_line_ids = fields.One2many(
        comodel_name="nn.approval.rule.line",
        inverse_name="rule_id",
        string="Rule Lines",
        copy=True,
    )

    # Keep backward-compatible fields
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

    step_ids = fields.One2many(
        comodel_name="nn.approval.step",
        inverse_name="rule_id",
        string="Approval Steps (Legacy)",
        copy=True,
    )

    _sql_constraints = [
        (
            "check_amount_range",
            "CHECK(max_amount >= min_amount)",
            "Maximum amount must be greater than or equal to minimum amount.",
        ),
    ]

    @api.depends("name", "request_type")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.name} ({record.request_type})"

    @api.model
    def _get_applicable_rule(self, request_type, amount, company_id):
        domain = [
            ("request_type", "=", request_type),
            ("min_amount", "<=", amount),
            ("max_amount", ">=", amount) if amount > 0 else ("max_amount", ">=", 0),
            ("active", "=", True),
            ("company_id", "=", company_id),
        ]
        if amount > 0:
            domain[2] = ("max_amount", ">=", amount)
        else:
            domain[2] = ("max_amount", ">=", 0)
        return self.search(domain, limit=1)


class ApprovalStep(models.Model):
    _name = "nn.approval.step"
    _description = "Approval Step"
    _order = "rule_id, sequence"
    _rec_name = "display_name"
    _check_company_auto = True

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    @api.depends("approver_type", "sequence")
    def _compute_display_name(self):
        for record in self:
            type_label = dict(record._fields["approver_type"].selection).get(
                record.approver_type, record.approver_type
            )
            record.display_name = f"Step {record.sequence}: {type_label}"

    rule_id = fields.Many2one(
        comodel_name="nn.approval.rule",
        string="Approval Rule",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sequence = fields.Integer(
        string="Sequence",
        required=True,
        default=10,
    )

    approver_type = fields.Selection(
        selection=[
            ("gm", "GM Approver"),
            ("md", "MD Approver"),
        ],
        string="Approver Type",
        required=True,
    )

    approver_group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Approver Group",
        required=True,
        domain=[
            ("name", "in", ["GM Approver", "MD Approver"]),
        ],
        help="The group whose members can approve at this step.",
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="rule_id.company_id",
        store=True,
        index=True,
    )

    def _get_approvers(self):
        """Return users who can approve at this step (backward compat)."""
        if self.approver_group_id:
            return self.approver_group_id.users
        return self.env["res.users"]

    def _user_can_approve(self, user=None):
        """Check if user can approve at this step (backward compat)."""
        if user is None:
            user = self.env.user
        if not self.approver_group_id:
            return False
        return user in self.approver_group_id.users

    _sql_constraints = [
        (
            "unique_sequence_per_rule",
            "UNIQUE(rule_id, sequence)",
            "Sequence must be unique per rule.",
        ),
    ]


class ApprovalRuleLine(models.Model):
    _name = "nn.approval.rule.line"
    _description = "Approval Rule Line"
    _order = "rule_id, sequence"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    rule_id = fields.Many2one(
        comodel_name="nn.approval.rule",
        string="Approval Rule",
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
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    minimum_amount = fields.Monetary(
        string="Minimum Amount",
        required=True,
        default=0.0,
        currency_field="currency_id",
    )

    maximum_amount = fields.Monetary(
        string="Maximum Amount",
        required=True,
        default=0.0,
        currency_field="currency_id",
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project Scope",
        check_company=True,
        help="Leave empty to apply to all projects.",
    )

    expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Expense Head Scope",
        check_company=True,
        help="Leave empty to apply to all expense heads.",
    )

    approver_type = fields.Selection(
        selection=[
            ("user", "User"),
            ("group", "Group"),
        ],
        string="Approver Type",
        required=True,
        default="group",
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        domain=[("share", "=", False)],
        help="Specific user who must approve at this step.",
    )

    group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Approver Group",
        help="Group whose members can approve at this step.",
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="rule_id.company_id",
        store=True,
        index=True,
    )

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        related="rule_id.currency_id",
        store=True,
    )

    _sql_constraints = [
        (
            "check_amount_range",
            "CHECK(maximum_amount >= minimum_amount)",
            "Maximum amount must be >= minimum amount.",
        ),
        (
            "check_user_required",
            "CHECK(approver_type != 'user' OR user_id IS NOT NULL)",
            "User approver must be specified when approver type is 'User'.",
        ),
        (
            "check_group_required",
            "CHECK(approver_type != 'group' OR group_id IS NOT NULL)",
            "Group approver must be specified when approver type is 'Group'.",
        ),
    ]

    @api.depends("approver_type", "sequence", "user_id", "group_id")
    def _compute_display_name(self):
        for record in self:
            if record.approver_type == "user" and record.user_id:
                record.display_name = (
                    f"Step {record.sequence}: {record.user_id.name}"
                )
            elif record.approver_type == "group" and record.group_id:
                record.display_name = (
                    f"Step {record.sequence}: {record.group_id.name}"
                )
            else:
                record.display_name = f"Step {record.sequence}: (unassigned)"

    def _get_approvers(self):
        self.ensure_one()
        if self.approver_type == "user" and self.user_id:
            return self.user_id
        if self.approver_type == "group" and self.group_id:
            return self.group_id.users
        return self.env["res.users"]

    def _user_can_approve(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if self.approver_type == "user" and self.user_id:
            return user.id == self.user_id.id
        if self.approver_type == "group" and self.group_id:
            return self.group_id.id in user.groups_id.ids
        return False
