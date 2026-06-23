from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AuditLog(models.Model):
    _name = "nn.audit.log"
    _description = "Audit Log"
    _order = "date DESC, id DESC"
    _rec_name = "display_name"
    _check_company_auto = True
    _inherit = ["nn.security.mixin"]

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    model = fields.Char(
        string="Model",
        required=True,
        index=True,
    )

    res_id = fields.Integer(
        string="Record ID",
        required=True,
        index=True,
    )

    reference = fields.Char(
        string="Reference",
        index=True,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )

    date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    action = fields.Selection(
        selection=[
            ("create", "Create"),
            ("write", "Write"),
            ("unlink", "Delete"),
            ("confirm", "Confirm"),
            ("reverse", "Reverse"),
            ("submit", "Submit"),
            ("approve", "Approve"),
            ("reject", "Reject"),
            ("cancel", "Cancel"),
            ("post", "Post"),
            ("close", "Close"),
            ("transfer", "Transfer"),
            ("other", "Other"),
        ],
        string="Action",
        required=True,
        index=True,
    )

    previous_state = fields.Char(
        string="Previous State",
    )

    new_state = fields.Char(
        string="New State",
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

    description = fields.Text(
        string="Description",
    )

    @api.depends("model", "reference", "action")
    def _compute_display_name(self):
        for record in self:
            model_short = record.model.replace("nn.", "").replace(".", " ").title()
            record.display_name = (
                f"[{record.reference or 'N/A'}] {model_short} - {record.action}"
            )

    def write(self, vals):
        """Audit records are IMMUTABLE. No modifications allowed after creation.

        This is a critical financial control — audit trails must be
        tamper-proof to maintain legal and regulatory compliance.
        """
        raise UserError(
            _("Audit log records are immutable and cannot be modified after creation.")
        )

    def unlink(self):
        """Audit records are IMMUTABLE. No deletions allowed.

        Consistent with financial record-keeping regulations requiring
        permanent, unalterable audit trails.
        """
        raise UserError(
            _("Audit log records are immutable and cannot be deleted.")
        )

    @api.model
    def _log(
        self,
        model,
        res_id,
        action,
        reference=None,
        previous_state=None,
        new_state=None,
        amount=0.0,
        fund_account_id=None,
        project_id=None,
        expense_head_id=None,
        description=None,
    ):
        self.create(
            {
                "model": model,
                "res_id": res_id,
                "reference": reference,
                "user_id": self.env.user.id,
                "action": action,
                "previous_state": previous_state,
                "new_state": new_state,
                "amount": amount,
                "fund_account_id": fund_account_id,
                "project_id": project_id,
                "expense_head_id": expense_head_id,
                "company_id": self.env.company.id,
                "description": description,
            }
        )
