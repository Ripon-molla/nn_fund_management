from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundAccount(models.Model):
    _name = "nn.fund.account"
    _description = "Fund Account"
    _order = "code, name"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    name = fields.Char(
        string="Account Name",
        required=True,
        tracking=True,
    )

    code = fields.Char(
        string="Account Code",
        required=True,
        index=True,
        tracking=True,
    )

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    type = fields.Selection(
        selection=[
            ("main", "Main Fund"),
            ("project", "Project Fund"),
            ("restricted", "Restricted Fund"),
            ("petty_cash", "Petty Cash"),
        ],
        string="Account Type",
        required=True,
        default="main",
        tracking=True,
    )

    parent_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Parent Account",
        index=True,
        tracking=True,
        check_company=True,
    )

    child_ids = fields.One2many(
        comodel_name="nn.fund.account",
        inverse_name="parent_id",
        string="Child Accounts",
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

    notes = fields.Text(
        string="Notes",
        tracking=True,
    )

    is_closed = fields.Boolean(
        string="Closed",
        default=False,
        tracking=True,
        help="When closed, no new transactions can be posted to this account.",
    )

    current_balance = fields.Monetary(
        string="Current Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Total ledger balance (SUM of all posted debits - credits) for this account.",
    )

    available_balance = fields.Monetary(
        string="Available Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Balance available for new allocations and commitments.",
    )

    held_balance = fields.Monetary(
        string="Held Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Amount held by pending (unapproved) requests.",
    )

    assigned_balance = fields.Monetary(
        string="Assigned Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Amount assigned to approved allocations.",
    )

    spent_balance = fields.Monetary(
        string="Spent Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Amount spent via posted bills.",
    )

    transfer_hold_balance = fields.Monetary(
        string="Transfer Hold Balance",
        compute="_compute_balances",
        currency_field="currency_id",
        store=False,
        help="Amount held by pending fund transfers.",
    )

    ledger_entry_ids = fields.One2many(
        comodel_name="nn.fund.ledger",
        inverse_name="fund_account_id",
        string="Ledger Entries",
        readonly=True,
    )

    ledger_count = fields.Integer(
        string="Ledger Entries Count",
        compute="_compute_ledger_count",
    )

    _sql_constraints = [
        (
            "code_unique_per_company",
            "UNIQUE(code, company_id)",
            "Account code must be unique per company.",
        ),
    ]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            if record.code and record.name:
                record.display_name = f"[{record.code}] {record.name}"
            elif record.name:
                record.display_name = record.name
            else:
                record.display_name = _("New")

    @api.depends("ledger_entry_ids")
    def _compute_ledger_count(self):
        for record in self:
            record.ledger_count = len(record.ledger_entry_ids)

    def _compute_balances(self):
        Ledger = self.env["nn.fund.ledger"]
        for account in self:
            posted_entries = Ledger.search(
                [
                    ("fund_account_id", "=", account.id),
                    ("state", "=", "posted"),
                ]
            )
            all_debits = sum(posted_entries.mapped("debit"))
            all_credits = sum(posted_entries.mapped("credit"))
            current_balance = all_debits - all_credits

            aggregates = posted_entries.read_group(
                [("id", "in", posted_entries.ids)],
                ["transaction_type", "debit:sum", "credit:sum"],
                ["transaction_type"],
            )
            type_totals = {}
            for agg in aggregates:
                type_totals[agg["transaction_type"]] = {
                    "debit": agg["debit"] or 0.0,
                    "credit": agg["credit"] or 0.0,
                }

            allocation_hold = type_totals.get("allocation_hold", {}).get("credit", 0.0)
            allocation_release = type_totals.get("allocation_release", {}).get("debit", 0.0)
            allocation_approve = type_totals.get("allocation_approve", {}).get("credit", 0.0)
            transfer_hold = type_totals.get("transfer_hold", {}).get("credit", 0.0)
            transfer_release = type_totals.get("transfer_release", {}).get("debit", 0.0)
            transfer_approve = type_totals.get("transfer_approve", {}).get("credit", 0.0)
            transfer_approved_out = type_totals.get("transfer_approved_out", {}).get("credit", 0.0)
            transfer_approved_in = type_totals.get("transfer_approved_in", {}).get("debit", 0.0)
            requisition_hold = type_totals.get("requisition_hold", {}).get("credit", 0.0)
            requisition_release = type_totals.get("requisition_release", {}).get("debit", 0.0)
            requisition_approved = type_totals.get("requisition_approved", {}).get("credit", 0.0)
            bill_post = type_totals.get("bill_posted", {}).get("credit", 0.0)
            bill_reversal = type_totals.get("bill_reversal", {}).get("debit", 0.0)

            held_balance = (
                allocation_hold
                + transfer_hold
                + requisition_hold
                - allocation_release
                - transfer_release
                - requisition_release
            )
            if held_balance < 0:
                held_balance = 0.0

            assigned_balance = allocation_approve + transfer_approve
            spent_balance = bill_post - bill_reversal
            if spent_balance < 0:
                spent_balance = 0.0

            transfer_hold_balance = transfer_hold - transfer_release
            if transfer_hold_balance < 0:
                transfer_hold_balance = 0.0

            available_balance = current_balance
            if available_balance < 0:
                available_balance = 0.0

            account.current_balance = current_balance
            account.held_balance = held_balance
            account.transfer_hold_balance = transfer_hold_balance
            account.assigned_balance = assigned_balance
            account.spent_balance = spent_balance
            account.available_balance = available_balance

    def action_open_ledger(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Ledger Entries"),
            "res_model": "nn.fund.ledger",
            "view_mode": "list,form",
            "domain": [("fund_account_id", "=", self.id)],
            "context": {
                "default_fund_account_id": self.id,
            },
        }

    def action_check_financial_consistency(self):
        """Run a financial consistency check on this account.

        Cross-validates ledger-derived balances against stored balances,
        checks for orphans, duplicates, and negative balances.

        Returns:
            dict: Action to display results
        """
        self.ensure_one()
        result = self.env["nn.security.mixin"]._check_financial_consistency(
            account_id=self.id
        )
        log_msg = _("Consistent") if result["consistent"] else _("INCONSISTENT (%d violations)") % result["violation_count"]
        self.env["nn.audit.log"]._log(
            model=self._name,
            res_id=self.id,
            action="consistency_check",
            reference="CHK-%s-%s" % (self.code, fields.Datetime.now()),
            description=_("Financial consistency check for %(account)s: %(status)s")
            % {"account": self.display_name, "status": log_msg},
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Consistency Check: %s") % self.display_name,
            "res_model": "nn.audit.log",
            "view_mode": "list,form",
            "domain": [
                ("model", "=", self._name),
                ("res_id", "=", self.id),
                ("action", "=", "consistency_check"),
            ],
        }
