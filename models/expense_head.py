from odoo import api, fields, models, _


class ExpenseHead(models.Model):
    _name = "nn.expense.head"
    _description = "Expense Head"
    _order = "code, name"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    name = fields.Char(
        string="Expense Head",
        required=True,
        tracking=True,
    )

    code = fields.Char(
        string="Code",
        required=True,
        index=True,
        tracking=True,
    )

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project",
        required=True,
        tracking=True,
        check_company=True,
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

    allocated_amount = fields.Monetary(
        string="Allocated Amount",
        compute="_compute_expense_balances",
        currency_field="currency_id",
    )

    spent_amount = fields.Monetary(
        string="Spent Amount",
        compute="_compute_expense_balances",
        currency_field="currency_id",
    )

    remaining_amount = fields.Monetary(
        string="Remaining Amount",
        compute="_compute_expense_balances",
        currency_field="currency_id",
    )

    notes = fields.Text(
        string="Notes",
        tracking=True,
    )

    _sql_constraints = [
        (
            "code_unique_per_project",
            "UNIQUE(code, project_id, company_id)",
            "Expense head code must be unique per project.",
        ),
    ]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"

    @api.depends("project_id")
    def _compute_expense_balances(self):
        Allocation = self.env["nn.fund.allocation"]
        Bill = self.env["nn.fund.bill"]
        for record in self:
            approved_allocations = Allocation.search(
                [
                    ("project_id", "=", record.project_id.id),
                    ("state", "=", "approved"),
                ]
            )
            record.allocated_amount = sum(
                approved_allocations.mapped("amount")
            )
            posted_bills = Bill.search(
                [
                    ("expense_head_id", "=", record.id),
                    ("state", "=", "posted"),
                ]
            )
            record.spent_amount = sum(posted_bills.mapped("amount"))
            record.remaining_amount = (
                record.allocated_amount - record.spent_amount
            )
