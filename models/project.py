from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Project(models.Model):
    _name = "nn.project"
    _description = "Fund Project"
    _order = "code, name"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    name = fields.Char(
        string="Project Name",
        required=True,
        tracking=True,
    )

    code = fields.Char(
        string="Project Code",
        required=True,
        index=True,
        tracking=True,
    )

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
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

    is_closed = fields.Boolean(
        string="Closed",
        default=False,
        tracking=True,
    )

    start_date = fields.Date(
        string="Start Date",
        tracking=True,
    )

    end_date = fields.Date(
        string="End Date",
        tracking=True,
    )

    allocated_amount = fields.Monetary(
        string="Allocated Amount",
        compute="_compute_project_balances",
        currency_field="currency_id",
        store=False,
    )

    spent_amount = fields.Monetary(
        string="Spent Amount",
        compute="_compute_project_balances",
        currency_field="currency_id",
        store=False,
    )

    remaining_amount = fields.Monetary(
        string="Remaining Amount",
        compute="_compute_project_balances",
        currency_field="currency_id",
        store=False,
    )

    expense_head_ids = fields.One2many(
        comodel_name="nn.expense.head",
        inverse_name="project_id",
        string="Expense Heads",
    )

    notes = fields.Text(
        string="Notes",
        tracking=True,
    )

    _sql_constraints = [
        (
            "code_unique_per_company",
            "UNIQUE(code, company_id)",
            "Project code must be unique per company.",
        ),
    ]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"[{record.code}] {record.name}"

    available_balance = fields.Monetary(
        string="Available Balance",
        compute="_compute_project_balances",
        currency_field="currency_id",
        store=False,
        help="Available balance computed from posted ledger entries for this project.",
    )

    @api.depends("fund_account_id")
    def _compute_project_balances(self):
        Ledger = self.env["nn.fund.ledger"]
        Allocation = self.env["nn.fund.allocation"]
        Bill = self.env["nn.fund.bill"]
        for record in self:
            approved_allocations = Allocation.search(
                [
                    ("project_id", "=", record.id),
                    ("state", "=", "approved"),
                ]
            )
            record.allocated_amount = sum(
                approved_allocations.mapped("amount")
            )
            posted_bills = Bill.search(
                [
                    ("project_id", "=", record.id),
                    ("state", "=", "posted"),
                ]
            )
            record.spent_amount = sum(posted_bills.mapped("amount"))
            record.remaining_amount = (
                record.allocated_amount - record.spent_amount
            )
            posted_ledger = Ledger.search(
                [
                    ("project_id", "=", record.id),
                    ("state", "=", "posted"),
                ]
            )
            total_debit = sum(posted_ledger.mapped("debit"))
            total_credit = sum(posted_ledger.mapped("credit"))
            record.available_balance = total_debit - total_credit
