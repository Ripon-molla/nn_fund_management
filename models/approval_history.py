from odoo import api, fields, models, _


class ApprovalHistory(models.Model):
    _name = "nn.approval.history"
    _description = "Approval History"
    _order = "date DESC, id DESC"
    _rec_name = "display_name"
    _check_company_auto = True
    _inherit = ["nn.security.mixin"]

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
        index=True,
    )

    request_id = fields.Integer(
        string="Request ID",
        required=True,
        index=True,
    )

    request_reference = fields.Char(
        string="Request Reference",
        required=True,
        index=True,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )

    # Dynamic approval level — stores group name or "Auto"/"System"
    approval_level = fields.Char(
        string="Approval Level",
        required=True,
        default="System",
        index=True,
        help="Name of the approving group, or 'Auto'/'System' for automatic transitions.",
    )

    matrix_line_id = fields.Many2one(
        comodel_name="nn.approval.matrix.line",
        string="Matrix Line",
        index=True,
        readonly=True,
        help="The approval matrix line that was used for this step.",
    )

    rule_line_id = fields.Many2one(
        comodel_name="nn.approval.rule.line",
        string="Rule Line",
        index=True,
        readonly=True,
        help="The approval rule line that was used for this step.",
    )

    previous_state = fields.Char(
        string="Previous State",
        required=True,
    )

    new_state = fields.Char(
        string="New State",
        required=True,
    )

    date = fields.Datetime(
        string="Approval Date",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        index=True,
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project",
        index=True,
    )

    expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Expense Head",
        index=True,
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

    comment = fields.Text(
        string="Comment",
    )

    @api.depends("request_type", "request_reference", "new_state", "approval_level")
    def _compute_display_name(self):
        for record in self:
            type_label = dict(
                record._fields["request_type"].selection
            ).get(record.request_type, record.request_type)
            record.display_name = (
                f"[{record.request_reference}] {type_label} "
                f"[{record.approval_level}] -> {record.new_state}"
            )

    @api.model
    def _log_approval(
        self,
        request_type,
        request_id,
        request_reference,
        previous_state,
        new_state,
        amount=0.0,
        fund_account_id=None,
        project_id=None,
        expense_head_id=None,
        comment=None,
        approval_level="System",
        matrix_line_id=None,
        rule_line_id=None,
    ):
        vals = {
            "request_type": request_type,
            "request_id": request_id,
            "request_reference": request_reference,
            "user_id": self.env.user.id,
            "approval_level": approval_level,
            "previous_state": previous_state,
            "new_state": new_state,
            "amount": amount,
            "fund_account_id": fund_account_id,
            "project_id": project_id,
            "expense_head_id": expense_head_id,
            "comment": comment,
            "company_id": self.env.company.id,
        }
        if matrix_line_id:
            vals["matrix_line_id"] = matrix_line_id
        if rule_line_id:
            vals["rule_line_id"] = rule_line_id
        self.create(vals)
