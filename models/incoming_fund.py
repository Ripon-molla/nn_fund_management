from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class IncomingFund(models.Model):
    _name = "nn.incoming.fund"
    _description = "Incoming Fund"
    _order = "received_date DESC, id DESC"
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
        default=lambda self: _("New"),
        copy=False,
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        required=True,
        tracking=True,
        check_company=True,
        domain=[("active", "=", True), ("is_closed", "=", False)],
    )

    amount = fields.Monetary(
        string="Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )

    received_date = fields.Date(
        string="Received Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    source_type = fields.Selection(
        selection=[
            ("donor", "Donor Contribution"),
            ("budget", "Budget Allocation"),
            ("transfer", "Transfer"),
            ("grant", "Grant"),
            ("internal", "Internal Transfer"),
            ("other", "Other"),
        ],
        string="Source Type",
        required=True,
        default="donor",
        tracking=True,
    )

    source_reference = fields.Char(
        string="Source Reference",
        tracking=True,
        help="External reference number from the source.",
    )

    donor_name = fields.Char(
        string="Donor Name",
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending_verification", "Pending Verification"),
            ("confirmed", "Confirmed"),
            ("reversed", "Reversed"),
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
        help="The ledger entry created when this fund was confirmed.",
    )

    reversal_ledger_entry_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Reversal Ledger Entry",
        readonly=True,
        help="The ledger entry created when this fund was reversed.",
    )

    _sql_constraints = [
        (
            "reference_unique_per_company",
            "UNIQUE(reference, company_id)",
            "Reference must be unique per company.",
        ),
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "Incoming fund amount must be positive.",
        ),
    ]

    @api.constrains("fund_account_id", "state")
    def _check_fund_account_active(self):
        for record in self:
            if record.fund_account_id.is_closed and record.state in (
                "confirmed", "pending_verification"
            ):
                raise ValidationError(
                    _(
                        "Cannot confirm incoming fund to a closed account: %s"
                    )
                    % record.fund_account_id.display_name
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            ref = vals.get("reference")
            if not ref or ref == _("New"):
                vals["reference"] = self._get_next_reference()
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {
            "amount",
            "fund_account_id",
            "received_date",
            "source_type",
            "reference",
            "source_reference",
        }
        always_allowed = {
            "notes",
            "state",
            "ledger_entry_id",
            "is_verified",
            "verified_by",
            "verified_date",
            "message_ids",
            "message_follower_ids",
            "activity_ids",
            "reversal_ledger_entry_id",
        }
        for record in self:
            if record.state == "confirmed":
                actually_changed = []
                for fname, new_val in vals.items():
                    if fname in always_allowed:
                        continue
                    curr_val = record[fname]
                    if new_val != curr_val:
                        actually_changed.append(fname)
                forbidden = [f for f in actually_changed if f in protected_fields]
                if forbidden:
                    raise ValidationError(
                        _(
                            "Cannot modify %(field)s on a confirmed incoming fund."
                        )
                        % {"field": ", ".join(sorted(forbidden))}
                    )
        return super().write(vals)

    def _get_next_reference(self):
        seq = self.env["ir.sequence"].next_by_code("nn.incoming.fund") or "/"
        return seq

    def action_verify(self):
        """Verify a pending_verification incoming fund.

        Transitions from pending_verification → confirmed.
        Creates ledger entry (debit) for the fund account.
        Finance users verify that the bank notification matches
        the actual bank statement before confirming.
        """
        self.ensure_one()
        if self.state != "pending_verification":
            raise ValidationError(
                _("Only pending verification incoming funds can be verified.")
            )
        return self.action_confirm()

    def action_confirm(self):
        self.ensure_one()
        if self.state not in ("draft", "pending_verification"):
            raise ValidationError(
                _("Only draft or pending verification incoming funds can be confirmed.")
            )
        if self.fund_account_id.is_closed:
            raise ValidationError(
                _("Cannot confirm incoming fund to a closed account.")
            )
        if self.amount <= 0:
            raise ValidationError(
                _("Incoming fund amount must be positive.")
            )
        self._acquire_row_lock(self.fund_account_id.id)
        ledger = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference,
                "transaction_type": "incoming",
                "fund_account_id": self.fund_account_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": self.amount,
                "credit": 0.0,
                "note": self.notes or "",
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.write(
            {
                "state": "confirmed",
                "ledger_entry_id": ledger.id,
            }
        )
        self.fund_account_id.invalidate_recordset(
            [
                "current_balance",
                "available_balance",
                "held_balance",
                "assigned_balance",
                "spent_balance",
                "transfer_hold_balance",
            ]
        )
        return True

    def action_reverse(self):
        self.ensure_one()
        if self.state != "confirmed":
            raise ValidationError(
                _("Only confirmed incoming funds can be reversed.")
            )
        if self.fund_account_id.current_balance < self.amount:
            raise ValidationError(
                _(
                    "Insufficient balance in the fund account to reverse this incoming fund."
                )
            )
        self._acquire_row_lock(self.fund_account_id.id)
        self._validate_available_balance(self.fund_account_id, self.amount)
        reverse_ledger = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-REV",
                "transaction_type": "incoming",
                "fund_account_id": self.fund_account_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": self.notes
                and self.notes + "\nReversal of incoming fund."
                or "Reversal of incoming fund.",
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        if self.ledger_entry_id:
            self.ledger_entry_id.write({"state": "reversed"})
        self.write(
            {
                "state": "reversed",
                "reversal_ledger_entry_id": reverse_ledger.id,
            }
        )
        self.env["nn.fund.ledger"]._verify_reversal_integrity(
            original=self.ledger_entry_id, reversal=reverse_ledger
        )
        return True
