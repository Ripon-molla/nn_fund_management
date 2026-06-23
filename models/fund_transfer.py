from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundTransfer(models.Model):
    _name = "nn.fund.transfer"
    _description = "Fund Transfer"
    _order = "date DESC, id DESC"
    _rec_name = "reference"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "nn.notification.mixin",
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

    source_project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Source Project",
        index=True,
        tracking=True,
        check_company=True,
    )

    source_expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Source Expense Head",
        index=True,
        tracking=True,
        check_company=True,
    )

    source_fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Source Account",
        compute="_compute_source_fund_account",
        store=True,
        readonly=True,
        tracking=True,
        check_company=True,
    )

    destination_project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Destination Project",
        index=True,
        tracking=True,
        check_company=True,
    )

    destination_expense_head_id = fields.Many2one(
        comodel_name="nn.expense.head",
        string="Destination Expense Head",
        index=True,
        tracking=True,
        check_company=True,
    )

    destination_fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Destination Account",
        compute="_compute_dest_fund_account",
        store=True,
        readonly=True,
        tracking=True,
        check_company=True,
    )

    amount = fields.Monetary(
        string="Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )

    reason = fields.Text(
        string="Reason",
        tracking=True,
    )

    requested_by = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        tracking=True,
    )

    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        tracking=True,
    )

    date = fields.Date(
        string="Transfer Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        string="State",
        required=True,
        default="draft",
        index=True,
        tracking=True,
    )

    current_matrix_line_id = fields.Many2one(
        comodel_name="nn.approval.matrix.line",
        string="Current Approval Step",
        index=True,
        readonly=True,
        tracking=True,
    )

    current_rule_line_id = fields.Many2one(
        comodel_name="nn.approval.rule.line",
        string="Current Rule Step",
        index=True,
        readonly=True,
        tracking=True,
    )

    pending_approval_step = fields.Char(
        string="Current Step",
        compute="_compute_pending_approval_step",
    )

    @api.depends("state", "current_matrix_line_id", "current_rule_line_id")
    def _compute_pending_approval_step(self):
        for record in self:
            line = record.current_rule_line_id or record.current_matrix_line_id
            if record.state == "pending_approval" and line:
                record.pending_approval_step = line.display_name
            else:
                record.pending_approval_step = False

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

    source_ledger_entry_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Source Ledger Entry",
        readonly=True,
    )

    destination_ledger_entry_id = fields.Many2one(
        comodel_name="nn.fund.ledger",
        string="Destination Ledger Entry",
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
            "Transfer amount must be positive.",
        ),
    ]

    @api.depends("source_project_id", "source_expense_head_id")
    def _compute_source_fund_account(self):
        for record in self:
            if record.source_project_id:
                record.source_fund_account_id = record.source_project_id.fund_account_id
            elif record.source_expense_head_id:
                record.source_fund_account_id = (
                    record.source_expense_head_id.project_id.fund_account_id
                )
            else:
                record.source_fund_account_id = False

    @api.depends("destination_project_id", "destination_expense_head_id")
    def _compute_dest_fund_account(self):
        for record in self:
            if record.destination_project_id:
                record.destination_fund_account_id = (
                    record.destination_project_id.fund_account_id
                )
            elif record.destination_expense_head_id:
                record.destination_fund_account_id = (
                    record.destination_expense_head_id.project_id.fund_account_id
                )
            else:
                record.destination_fund_account_id = False

    def _compute_ledger_entry_ids(self):
        for record in self:
            record.ledger_entry_ids = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", record.id),
                ]
            )

    @api.constrains("source_project_id", "source_expense_head_id")
    def _check_source_xor(self):
        for record in self:
            if record.source_project_id and record.source_expense_head_id:
                if record.source_expense_head_id.project_id != record.source_project_id:
                    raise ValidationError(
                        _("Source expense head does not belong to source project.")
                    )
            if not record.source_project_id and not record.source_expense_head_id:
                raise ValidationError(
                    _("Either a source Project or Expense Head must be specified.")
                )

    @api.constrains("destination_project_id", "destination_expense_head_id")
    def _check_destination_xor(self):
        for record in self:
            if record.destination_project_id and record.destination_expense_head_id:
                if (
                    record.destination_expense_head_id.project_id
                    != record.destination_project_id
                ):
                    raise ValidationError(
                        _(
                            "Destination expense head does not belong to destination project."
                        )
                    )
            if not record.destination_project_id and not record.destination_expense_head_id:
                raise ValidationError(
                    _(
                        "Either a destination Project or Expense Head must be specified."
                    )
                )

    @api.constrains(
        "source_project_id",
        "source_expense_head_id",
        "destination_project_id",
        "destination_expense_head_id",
    )
    def _check_source_destination_same(self):
        for record in self:
            src_same_project = (
                record.source_project_id
                and record.destination_project_id
                and record.source_project_id.id == record.destination_project_id.id
            )
            src_same_expense = (
                record.source_expense_head_id
                and record.destination_expense_head_id
                and record.source_expense_head_id.id
                == record.destination_expense_head_id.id
            )
            if src_same_project or src_same_expense:
                raise ValidationError(
                    _("Source and destination cannot be the same.")
                )

    @api.constrains("source_fund_account_id", "destination_fund_account_id")
    def _check_different_accounts(self):
        for record in self:
            if (
                record.source_fund_account_id
                and record.destination_fund_account_id
                and record.source_fund_account_id.id
                == record.destination_fund_account_id.id
            ):
                raise ValidationError(
                    _(
                        "Source and destination must use different fund accounts. "
                        "Cannot transfer within the same account."
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = self._get_next_reference()
        records = super().create(vals_list)
        for record in records:
            record._log_audit("create", description="Transfer created")
        return records

    def _get_next_reference(self):
        seq = self.env["ir.sequence"].next_by_code("nn.fund.transfer") or "/"
        return seq

    def _log_audit(self, action, previous_state=None, new_state=None, description=None):
        self.ensure_one()
        self.env["nn.audit.log"]._log(
            model=self._name,
            res_id=self.id,
            action=action,
            reference=self.reference,
            previous_state=previous_state,
            new_state=new_state,
            amount=self.amount,
            project_id=self.source_project_id or self.destination_project_id,
            expense_head_id=self.source_expense_head_id or self.destination_expense_head_id,
            description=description or "%s transfer %s" % (action.title(), self.reference),
        )

    def _get_current_line(self):
        return self.current_rule_line_id or self.current_matrix_line_id

    def _get_approval_steps(self):
        matrix = self.env["nn.approval.matrix"]._get_applicable_matrix(
            self._name,
            self.amount,
            self.company_id.id,
            project_id=self.source_project_id.id if self.source_project_id else None,
            expense_head_id=self.source_expense_head_id.id if self.source_expense_head_id else None,
        )
        return self.env["nn.approval.matrix"]._get_valid_lines(matrix, self.amount)

    def action_submit(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(_("Only draft transfers can be submitted."))
        self._validate_available_balance(self.source_fund_account_id, self.amount)
        self._check_source_destination_same()
        self._check_different_accounts()
        self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-HOLD",
                "transaction_type": "transfer_hold",
                "fund_account_id": self.source_fund_account_id.id,
                "project_id": self.source_project_id.id,
                "expense_head_id": self.source_expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": self.reason or "Hold for transfer %s" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.write({"state": "submitted"})
        self._log_audit("submit", previous_state="draft", new_state="submitted")
        self.message_post(
            subject=_("Transfer %s Submitted") % self.reference,
            body=_("Transfer %s of %s has been submitted for approval.")
            % (self.reference, self.amount),
        )
        self._evaluate_approval_workflow()
        return True

    def _evaluate_approval_workflow(self):
        self.ensure_one()
        steps = self._get_approval_steps()
        if not steps:
            self._execute_transfer()
            return
        self._assign_approval_step(steps[0])

    def _assign_approval_step(self, line):
        self.ensure_one()
        previous_state = self.state
        vals = {"state": "pending_approval"}
        if line._name == "nn.approval.rule.line":
            vals["current_rule_line_id"] = line.id
            vals["current_matrix_line_id"] = False
        else:
            vals["current_matrix_line_id"] = line.id
            vals["current_rule_line_id"] = False
        self.write(vals)
        level_name = line.display_name
        self.env["nn.approval.history"]._log_approval(
            self._name,
            self.id,
            self.reference,
            previous_state,
            "pending_approval",
            amount=self.amount,
            fund_account_id=self.source_fund_account_id.id,
            project_id=self.source_project_id or self.destination_project_id,
            expense_head_id=self.source_expense_head_id or self.destination_expense_head_id,
            approval_level=level_name,
            matrix_line_id=line.id if line._name != "nn.approval.rule.line" else None,
            rule_line_id=line.id if line._name == "nn.approval.rule.line" else None,
        )
        approvers = line._get_approvers()
        for user in approvers:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Transfer %s Pending %s Approval")
                         % (self.reference, line.display_name),
                note=_(
                    "Transfer %(ref)s for %(amount)s requires %(step)s approval."
                ) % {"ref": self.reference, "amount": self.amount, "step": line.display_name},
                user_id=user.id,
            )

    def _execute_transfer(self):
        self.ensure_one()
        self._acquire_row_lock(self.source_fund_account_id.id)
        self._acquire_row_lock(self.destination_fund_account_id.id)
        hold_entries = self.env["nn.fund.ledger"].search(
            [
                ("reference_model", "=", self._name),
                ("reference_id", "=", self.id),
                ("transaction_type", "=", "transfer_hold"),
                ("state", "=", "posted"),
            ]
        )
        for hold in hold_entries:
            self.env["nn.fund.ledger"].create(
                {
                    "date": fields.Datetime.now(),
                    "reference": self.reference + "-REL",
                    "transaction_type": "transfer_release",
                    "fund_account_id": hold.fund_account_id.id,
                    "project_id": self.source_project_id.id,
                    "expense_head_id": self.source_expense_head_id.id,
                    "reference_model": self._name,
                    "reference_id": self.id,
                    "debit": self.amount,
                    "credit": 0.0,
                    "note": "Release hold for transfer %s" % self.reference,
                    "state": "posted",
                    "company_id": self.company_id.id,
                }
            )
        source_ledger = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-OUT",
                "transaction_type": "transfer_approved_out",
                "fund_account_id": self.source_fund_account_id.id,
                "project_id": self.source_project_id.id,
                "expense_head_id": self.source_expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": self.reason
                or "Transfer out to %s" % self.destination_fund_account_id.display_name,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        dest_ledger = self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-IN",
                "transaction_type": "transfer_approved_in",
                "fund_account_id": self.destination_fund_account_id.id,
                "project_id": self.destination_project_id.id,
                "expense_head_id": self.destination_expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": self.amount,
                "credit": 0.0,
                "note": self.reason
                or "Transfer in from %s" % self.source_fund_account_id.display_name,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.write(
            {
                "state": "approved",
                "current_matrix_line_id": False,
                "current_rule_line_id": False,
                "source_ledger_entry_id": source_ledger.id,
                "destination_ledger_entry_id": dest_ledger.id,
            }
        )
        self.env["nn.approval.history"]._log_approval(
            self._name,
            self.id,
            self.reference,
            "pending_approval",
            "approved",
            amount=self.amount,
            fund_account_id=self.source_fund_account_id.id,
            project_id=self.source_project_id or self.destination_project_id,
            expense_head_id=self.source_expense_head_id or self.destination_expense_head_id,
            approval_level="final",
        )
        self._log_audit(
            "transfer",
            previous_state="pending_approval",
            new_state="approved",
            description="Transfer %s executed from %s to %s"
            % (self.reference, self.source_fund_account_id.display_name,
               self.destination_fund_account_id.display_name),
        )
        self.message_post(
            subject=_("Transfer %s Approved") % self.reference,
            body=_("Transfer %s of %s has been approved and executed.")
            % (self.reference, self.amount),
        )
        self._notify_requester(
            _("Transfer %s Approved") % self.reference,
            _("Your transfer request %s for %s has been approved and funds transferred.")
            % (self.reference, self.amount),
        )

    def action_approve(self):
        self.ensure_one()
        if self.state != "pending_approval":
            raise ValidationError(
                _("Transfer is not in a pending approval state.")
            )
        self._check_approval_idempotency(self)
        line = self._get_current_line()
        if not line:
            self._execute_transfer()
            return True
        if not line._user_can_approve():
            raise ValidationError(
                _("You are not authorized to approve at step '%s'.")
                % line.display_name
            )
        steps = self._get_approval_steps()
        current_idx = None
        for idx, s in enumerate(steps):
            if s._name == line._name and s.id == line.id:
                current_idx = idx
                break
        if current_idx is not None and current_idx + 1 < len(steps):
            self._assign_approval_step(steps[current_idx + 1])
        else:
            self._execute_transfer()
        return True

    def action_reject(self):
        self.ensure_one()
        if self.state not in ("submitted", "pending_approval"):
            raise ValidationError(
                _("Transfer is not in a rejectable state.")
            )
        hold_entries = self.env["nn.fund.ledger"].search(
            [
                ("reference_model", "=", self._name),
                ("reference_id", "=", self.id),
                ("transaction_type", "=", "transfer_hold"),
                ("state", "=", "posted"),
            ]
        )
        for hold in hold_entries:
            self.env["nn.fund.ledger"].create(
                {
                    "date": fields.Datetime.now(),
                    "reference": self.reference + "-REL",
                    "transaction_type": "transfer_release",
                    "fund_account_id": hold.fund_account_id.id,
                    "project_id": self.source_project_id.id,
                    "expense_head_id": self.source_expense_head_id.id,
                    "reference_model": self._name,
                    "reference_id": self.id,
                    "debit": self.amount,
                    "credit": 0.0,
                    "note": "Release hold for rejected transfer %s" % self.reference,
                    "state": "posted",
                    "company_id": self.company_id.id,
                }
            )
        self.write({
            "state": "rejected",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self._log_audit(
            "reject",
            previous_state=self.state,
            new_state="rejected",
            description="Transfer %s rejected by %s"
            % (self.reference, self.env.user.name),
        )
        self.message_post(
            subject=_("Transfer %s Rejected") % self.reference,
            body=_("Transfer %s of %s has been rejected.")
            % (self.reference, self.amount),
        )
        self._notify_requester(
            _("Transfer %s Rejected") % self.reference,
            _("Your transfer request %s for %s has been rejected.")
            % (self.reference, self.amount),
        )

    def action_cancel(self):
        self.ensure_one()
        if self.state in ("approved", "rejected", "cancelled"):
            raise ValidationError(
                _("Cannot cancel transfer in current state.")
            )
        if self.state in ("submitted", "pending_approval"):
            hold_entries = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", self.id),
                    ("transaction_type", "=", "transfer_hold"),
                    ("state", "=", "posted"),
                ]
            )
            for hold in hold_entries:
                self.env["nn.fund.ledger"].create(
                    {
                        "date": fields.Datetime.now(),
                        "reference": self.reference + "-REL",
                        "transaction_type": "transfer_release",
                        "fund_account_id": hold.fund_account_id.id,
                        "project_id": self.source_project_id.id,
                        "expense_head_id": self.source_expense_head_id.id,
                        "reference_model": self._name,
                        "reference_id": self.id,
                        "debit": self.amount,
                        "credit": 0.0,
                        "note": "Release hold for cancelled transfer %s" % self.reference,
                        "state": "posted",
                        "company_id": self.company_id.id,
                    }
                )
        self.write({
            "state": "cancelled",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self._log_audit(
            "cancel",
            previous_state=self.state,
            new_state="cancelled",
            description="Transfer %s cancelled" % self.reference,
        )
        self._notify_requester(
            _("Transfer %s Cancelled") % self.reference,
            _("Your transfer request %s for %s has been cancelled.")
            % (self.reference, self.amount),
        )
