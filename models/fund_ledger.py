import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class FundLedger(models.Model):
    _name = "nn.fund.ledger"
    _description = "Fund Ledger Entry"
    _order = "date DESC, id DESC"
    _rec_name = "reference"
    _check_company_auto = True

    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]

    date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        index=True,
        tracking=True,
    )

    reference = fields.Char(
        string="Reference",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
    )

    transaction_type = fields.Selection(
        selection=[
            ("incoming", "Incoming Fund"),
            ("allocation_hold", "Allocation Hold"),
            ("allocation_release", "Allocation Release"),
            ("allocation_approve", "Allocation Approval"),
            ("transfer_hold", "Transfer Hold"),
            ("transfer_release", "Transfer Release"),
            ("transfer_approve", "Transfer Approval"),
            ("transfer_approved_out", "Transfer Approved Out"),
            ("transfer_approved_in", "Transfer Approved In"),
            ("requisition_hold", "Requisition Hold"),
            ("requisition_release", "Requisition Release"),
            ("requisition_approved", "Requisition Approved"),
            ("bill_posted", "Bill Posted"),
            ("bill_reversal", "Bill Reversal"),
        ],
        string="Transaction Type",
        required=True,
        index=True,
        tracking=True,
    )

    amount = fields.Monetary(
        string="Amount",
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        required=True,
        index=True,
        tracking=True,
        check_company=True,
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project",
        index=True,
        tracking=True,
        check_company=True,
    )

    expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Expense Head",
        index=True,
        tracking=True,
        check_company=True,
    )

    reference_model = fields.Char(
        string="Source Model",
        required=True,
        index=True,
        help="Technical name of the source model (e.g. nn.fund.allocation)",
    )

    reference_id = fields.Integer(
        string="Source Record ID",
        required=True,
        index=True,
        help="ID of the source record in the source model",
    )

    debit = fields.Monetary(
        string="Debit",
        required=True,
        default=0.0,
        currency_field="currency_id",
        tracking=True,
    )

    credit = fields.Monetary(
        string="Credit",
        required=True,
        default=0.0,
        currency_field="currency_id",
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

    note = fields.Text(
        string="Note",
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("posted", "Posted"),
            ("reversed", "Reversed"),
        ],
        string="State",
        required=True,
        default="draft",
        index=True,
        tracking=True,
    )

    reversal_ledger_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Reversal Entry",
        readonly=True,
        help="Reference to the reversal ledger entry if this was reversed",
    )

    transaction_uuid = fields.Char(
        string="Transaction UUID",
        required=True,
        index=True,
        readonly=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
        help="Universally unique identifier for idempotency and deduplication.",
    )

    _sql_constraints = [
        (
            "check_debit_credit_not_both_positive",
            "CHECK(debit = 0.0 OR credit = 0.0)",
            "Debit and credit cannot both be non-zero in a single ledger entry.",
        ),
        (
            "check_debit_credit_not_both_zero",
            "CHECK(debit != 0.0 OR credit != 0.0)",
            "Debit and credit cannot both be zero in a single ledger entry.",
        ),
        (
            "transaction_uuid_unique",
            "UNIQUE(transaction_uuid)",
            "Transaction UUID must be unique across all ledger entries. "
            "Duplicate detected — this transaction has already been recorded.",
        ),
    ]

    @api.depends("debit", "credit")
    def _compute_amount(self):
        for record in self:
            record.amount = max(record.debit, record.credit)

    @api.constrains("debit", "credit")
    def _check_debit_credit(self):
        for record in self:
            if record.debit < 0 or record.credit < 0:
                raise ValidationError(
                    _("Debit and credit amounts must be non-negative.")
                )

    @api.constrains("transaction_type", "debit", "credit")
    def _check_transaction_direction(self):
        debit_types = {
            "incoming",
            "allocation_release",
            "transfer_release",
            "transfer_approved_in",
            "requisition_release",
            "bill_reversal",
        }
        credit_types = {
            "allocation_hold",
            "allocation_approve",
            "transfer_hold",
            "transfer_approve",
            "transfer_approved_out",
            "requisition_hold",
            "requisition_approved",
            "bill_posted",
        }
        for record in self:
            if record.transaction_type in debit_types and record.debit <= 0:
                raise ValidationError(
                    _("Transaction type %s must have a debit entry.")
                    % record.transaction_type
                )
            if record.transaction_type in credit_types and record.credit <= 0:
                raise ValidationError(
                    _("Transaction type %s must have a credit entry.")
                    % record.transaction_type
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = self._get_next_reference()
            if not vals.get("reference_model"):
                raise ValidationError(
                    _("reference_model is required for ledger entries.")
                )
            if not vals.get("reference_id"):
                raise ValidationError(
                    _("reference_id is required for ledger entries.")
                )
        return super().create(vals_list)

    def _get_next_reference(self):
        seq = self.env["ir.sequence"].next_by_code("nn.fund.ledger") or "/"
        return seq

    def write(self, vals):
        for record in self:
            if record.state == "posted":
                allowed = {"state"}
                if set(vals.keys()) - allowed:
                    raise UserError(
                        _(
                            "Posted ledger entry %s cannot be modified. "
                            "Only state changes are allowed."
                        )
                        % record.reference
                    )
                if vals.get("state") and vals["state"] not in ("reversed",):
                    raise UserError(
                        _(
                            "Posted ledger entry %s can only transition to 'reversed'. "
                            "Cannot revert to '%s'."
                        )
                        % (record.reference, vals["state"])
                    )
            if record.state == "reversed":
                raise UserError(
                    _(
                        "Reversed ledger entry %s cannot be modified under any circumstances."
                    )
                    % record.reference
                )
        return super().write(vals)

    def unlink(self):
        posted = self.filtered(lambda r: r.state == "posted")
        if posted:
            raise UserError(
                _(
                    "Cannot delete posted ledger entries: %s"
                )
                % ", ".join(posted.mapped("reference"))
            )
        reversed_entries = self.filtered(lambda r: r.state == "reversed")
        if reversed_entries:
            raise UserError(
                _(
                    "Cannot delete reversed ledger entries: %s"
                )
                % ", ".join(reversed_entries.mapped("reference"))
            )
        return super().unlink()

    def action_post(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(_("Only draft ledger entries can be posted."))
        self.write({"state": "posted"})

    def action_reverse(self):
        self.ensure_one()
        if self.state != "posted":
            raise ValidationError(
                _("Only posted ledger entries can be reversed.")
            )
        reverse = self.copy(
            default={
                "debit": self.credit,
                "credit": self.debit,
                "reference": self.reference + "-REV",
                "state": "posted",
                "reversal_ledger_id": self.id,
                "transaction_uuid": str(uuid.uuid4()),
                "note": (self.note or "")
                + "\nReversed entry.",
            }
        )
        self.write({"state": "reversed"})
        self._verify_reversal_integrity(original=self, reversal=reverse)
        return reverse

    @api.model
    def _verify_reversal_integrity(self, original, reversal):
        """Verify reversal does not create or destroy money.

        Principle: A reversal must be the exact mirror image of the original.
        - Original debit → reversal credit (same amount)
        - Original credit → reversal debit (same amount)
        - Amounts must match exactly
        - Account must be the same
        - Net balance impact must be zero
        """
        if original.debit != reversal.credit:
            raise ValidationError(
                _("Reversal integrity violation: original debit %.2f != reversal credit %.2f")
                % (original.debit, reversal.credit)
            )
        if original.credit != reversal.debit:
            raise ValidationError(
                _("Reversal integrity violation: original credit %.2f != reversal debit %.2f")
                % (original.credit, reversal.debit)
            )
        if original.fund_account_id.id != reversal.fund_account_id.id:
            raise ValidationError(
                _("Reversal integrity violation: reversal must target the same fund account.")
            )
        net_impact = (original.debit - original.credit) + (reversal.debit - reversal.credit)
        if abs(net_impact) > 0.001:
            raise ValidationError(
                _(
                    "Reversal integrity violation: net financial impact is %.2f "
                    "(must be zero). Reversal would create or destroy money."
                )
                % net_impact
            )
