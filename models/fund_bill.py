from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundBill(models.Model):
    _name = "nn.fund.bill"
    _description = "Fund Bill"
    _order = "date DESC, id DESC"
    _rec_name = "reference"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    reference = fields.Char(
        string="Reference",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
    )

    requisition_id = fields.Many2one(
        comodel_name="nn.fund.requisition",
        string="Requisition",
        required=True,
        tracking=True,
        check_company=True,
        domain=[("state", "=", "approved")],
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        compute="_compute_fund_account_id",
        store=True,
        readonly=True,
        tracking=True,
        check_company=True,
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project",
        compute="_compute_project_id",
        store=True,
        readonly=True,
        tracking=True,
        check_company=True,
    )

    expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Expense Head",
        tracking=True,
        check_company=True,
    )

    amount = fields.Monetary(
        string="Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )

    date = fields.Date(
        string="Bill Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    vendor_name = fields.Char(
        string="Vendor",
        tracking=True,
    )

    invoice_reference = fields.Char(
        string="Invoice Reference",
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("posted", "Posted"),
            ("cancelled", "Cancelled"),
        ],
        string="State",
        required=True,
        default="draft",
        index=True,
        tracking=True,
    )

    notes = fields.Text(
        string="Notes",
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

    ledger_entry_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Ledger Entry",
        readonly=True,
    )

    cancellation_ledger_entry_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Cancellation Ledger Entry",
        readonly=True,
    )

    ledger_entry_ids = fields.One2many(
        comodel_name="nn.fund.ledger",
        inverse_name="reference_id",
        string="All Ledger Entries",
        compute="_compute_ledger_entry_ids",
        readonly=True,
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "Bill amount must be positive.",
        ),
    ]

    @api.depends("requisition_id")
    def _compute_fund_account_id(self):
        for record in self:
            record.fund_account_id = record.requisition_id.fund_account_id

    @api.depends("requisition_id")
    def _compute_project_id(self):
        for record in self:
            record.project_id = record.requisition_id.project_id

    def _compute_ledger_entry_ids(self):
        for record in self:
            record.ledger_entry_ids = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", record.id),
                ]
            )

    @api.constrains("requisition_id", "expense_head_id")
    def _check_cross_validation(self):
        for record in self:
            req = record.requisition_id
            if req.expense_head_id and record.expense_head_id:
                if req.expense_head_id.id != record.expense_head_id.id:
                    raise ValidationError(
                        _(
                            "Bill expense head must match the requisition expense head."
                        )
                    )
            if req.project_id and record.project_id:
                if req.project_id.id != record.project_id.id:
                    raise ValidationError(
                        _("Cannot bill across different projects.")
                    )

    @api.constrains("requisition_id", "amount", "state")
    def _check_overbilling(self):
        for record in self:
            if record.state == "posted":
                requisition = record.requisition_id
                if requisition.state not in ("approved",):
                    raise ValidationError(
                        _("Requisition must be approved to post a bill.")
                    )
                if record.amount > requisition.remaining_billable_amount:
                    raise ValidationError(
                        _(
                            "Bill amount (%s) exceeds remaining billable amount (%s) "
                            "on requisition %s."
                        )
                        % (
                            record.amount,
                            requisition.remaining_billable_amount,
                            requisition.reference,
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = self._get_next_reference()
        return super().create(vals_list)

    def _get_next_reference(self):
        seq = self.env["ir.sequence"].next_by_code("nn.fund.bill") or "/"
        return seq

    def action_post(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(_("Only draft bills can be posted."))
        if self.requisition_id.state != "approved":
            raise ValidationError(
                _("Requisition must be approved before posting bills.")
            )
        remaining = self.requisition_id.remaining_billable_amount
        if self.amount > remaining:
            raise ValidationError(
                _(
                    "Bill amount (%s) exceeds remaining billable amount (%s) "
                    "on requisition %s."
                )
                % (
                    self.amount,
                    remaining,
                    self.requisition_id.reference,
                )
            )
        self._acquire_row_lock(self.fund_account_id.id)
        ledger = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference,
                "transaction_type": "bill_posted",
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": self.notes or "Bill %s posted" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.write(
            {
                "state": "posted",
                "ledger_entry_id": ledger.id,
            }
        )
        req = self.requisition_id
        if req.approved_amount > 0:
            remaining_ratio = req.remaining_billable_amount / req.approved_amount
            if remaining_ratio < 0.10:
                subject = _("Requisition %s Near Exhaustion") % req.reference
                message = _(
                    "Bill %(bill)s posted against requisition %(ref)s.\n"
                    "Remaining billable amount is now %(remaining)s "
                    "(%(ratio)s%% of approved %(approved)s)."
                ) % {
                    "bill": self.reference,
                    "ref": req.reference,
                    "remaining": req.remaining_billable_amount,
                    "ratio": round(remaining_ratio * 100, 1),
                    "approved": req.approved_amount,
                }
                req._notify_requester(subject, message)
                req.message_post(subject=subject, body=message)
        return True

    def action_cancel(self):
        self.ensure_one()
        if self.state != "posted":
            raise ValidationError(
                _("Only posted bills can be cancelled.")
            )
        reversal = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-CNL",
                "transaction_type": "bill_reversal",
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": self.amount,
                "credit": 0.0,
                "note": self.notes
                and self.notes + "\nCancellation of bill %s" % self.reference
                or "Cancellation of bill %s" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        if self.ledger_entry_id:
            self.ledger_entry_id.write({"state": "reversed"})
        self.write(
            {
                "state": "cancelled",
                "cancellation_ledger_entry_id": reversal.id,
            }
        )
        return True
