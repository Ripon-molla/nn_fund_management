import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundRequisition(models.Model):
    _name = "nn.fund.requisition"
    _description = "Fund Requisition"
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

    allocation_id = fields.Many2one(
        comodel_name="nn.fund.allocation",
        string="Fund Allocation",
        index=True,
        tracking=True,
        check_company=True,
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

    amount = fields.Monetary(
        string="Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )

    approved_amount = fields.Monetary(
        string="Approved Amount",
        readonly=True,
        tracking=True,
        currency_field="currency_id",
        help="Amount approved for this requisition. Set at time of approval.",
    )

    released_amount = fields.Monetary(
        string="Released Amount",
        default=0.0,
        readonly=True,
        tracking=True,
        currency_field="currency_id",
        help="Amount released back to available balance on close.",
    )

    remaining_billable_amount = fields.Monetary(
        string="Remaining Billable",
        compute="_compute_remaining_billable",
        store=True,
        currency_field="currency_id",
        help="Approved amount minus sum of posted bills minus released amount.",
    )

    date = fields.Date(
        string="Requisition Date",
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
            ("closed", "Closed"),
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

    bill_ids = fields.One2many(
        comodel_name="nn.fund.bill",
        inverse_name="requisition_id",
        string="Bills",
    )

    billed_amount = fields.Monetary(
        string="Billed Amount",
        compute="_compute_remaining_billable",
        currency_field="currency_id",
        store=False,
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

    ledger_entry_ids = fields.One2many(
        comodel_name="nn.fund.ledger",
        inverse_name="reference_id",
        string="Ledger Entries",
        compute="_compute_ledger_entry_ids",
        readonly=True,
    )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "Requisition amount must be positive.",
        ),
    ]

    @api.depends("project_id", "expense_head_id")
    def _compute_fund_account_id(self):
        for record in self:
            if record.project_id:
                record.fund_account_id = record.project_id.fund_account_id
            elif record.expense_head_id:
                record.fund_account_id = (
                    record.expense_head_id.project_id.fund_account_id
                )
            else:
                record.fund_account_id = False

    def _compute_ledger_entry_ids(self):
        for record in self:
            record.ledger_entry_ids = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", record.id),
                ]
            )

    @api.depends(
        "approved_amount",
        "released_amount",
        "bill_ids.amount",
        "bill_ids.state",
    )
    def _compute_remaining_billable(self):
        for record in self:
            posted_bills = record.bill_ids.filtered(lambda b: b.state == "posted")
            total_billed = sum(posted_bills.mapped("amount"))
            record.billed_amount = total_billed
            record.remaining_billable_amount = (
                record.approved_amount - total_billed - record.released_amount
            )

    @api.constrains("project_id", "expense_head_id")
    def _check_project_expense_xor(self):
        for record in self:
            if record.project_id and record.expense_head_id:
                if record.expense_head_id.project_id != record.project_id:
                    raise ValidationError(
                        _(
                            "Expense head %s does not belong to project %s."
                        )
                        % (record.expense_head_id.display_name, record.project_id.display_name)
                    )
            if not record.project_id and not record.expense_head_id:
                raise ValidationError(
                    _("Either a Project or an Expense Head must be specified.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = self._get_next_reference()
        return super().create(vals_list)

    def _get_next_reference(self):
        seq = self.env["ir.sequence"].next_by_code("nn.fund.requisition") or "/"
        return seq

    def action_submit(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(_("Only draft requisitions can be submitted."))
        self._check_project_expense_xor()
        self._validate_available_balance(self.fund_account_id, self.amount)
        self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-HOLD",
                "transaction_type": "requisition_hold",
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": self.notes
                or "Hold for requisition %s" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.write({"state": "submitted"})
        self._evaluate_approval_workflow()
        return True

    def _get_current_line(self):
        return self.current_rule_line_id or self.current_matrix_line_id

    def _get_approval_steps(self):
        matrix = self.env["nn.approval.matrix"]._get_applicable_matrix(
            self._name,
            self.amount,
            self.company_id.id,
            project_id=self.project_id.id if self.project_id else None,
            expense_head_id=self.expense_head_id.id if self.expense_head_id else None,
        )
        return self.env["nn.approval.matrix"]._get_valid_lines(matrix, self.amount)

    def _evaluate_approval_workflow(self):
        self.ensure_one()
        steps = self._get_approval_steps()
        if not steps:
            self._skip_to_approved()
            return
        self._assign_approval_step(steps[0])

    def _skip_to_approved(self):
        self._create_approval_ledger_entries()
        self.write({
            "state": "approved",
            "approved_amount": self.amount,
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self.message_post(
            subject=_("Requisition %s Approved") % self.reference,
            body=_("Requisition %s for %s has been approved.")
            % (self.reference, self.amount),
        )
        self._notify_requester(
            _("Requisition %s Approved") % self.reference,
            _("Your requisition %s for %s has been approved.")
            % (self.reference, self.amount),
        )

    def _create_approval_ledger_entries(self):
        self.ensure_one()
        self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-REL",
                "transaction_type": "requisition_release",
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": self.amount,
                "credit": 0.0,
                "note": "Release hold for approved requisition %s" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )
        self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.reference + "-APPR",
                "transaction_type": "requisition_approved",
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": 0.0,
                "credit": self.amount,
                "note": "Approved amount for requisition %s" % self.reference,
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )

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
            request_type=self._name,
            request_id=self.id,
            request_reference=self.reference,
            previous_state=previous_state,
            new_state="pending_approval",
            amount=self.amount,
            fund_account_id=self.fund_account_id.id,
            project_id=self.project_id.id,
            expense_head_id=self.expense_head_id.id,
            approval_level=level_name,
            matrix_line_id=line.id if line._name != "nn.approval.rule.line" else None,
            rule_line_id=line.id if line._name == "nn.approval.rule.line" else None,
        )
        approvers = line._get_approvers()
        for user in approvers:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Requisition %s Pending %s Approval")
                         % (self.reference, line.display_name),
                note=_(
                    "Requisition %(ref)s for %(amount)s requires %(step)s approval."
                ) % {"ref": self.reference, "amount": self.amount, "step": line.display_name},
                user_id=user.id,
            )

    def action_approve(self):
        self.ensure_one()
        if self.state != "pending_approval":
            raise ValidationError(
                _("Requisition is not in a pending approval state.")
            )
        self._check_approval_idempotency(self)
        line = self._get_current_line()
        if not line:
            self._skip_to_approved()
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
            self._skip_to_approved()
        return True

    def action_reject(self):
        self.ensure_one()
        if self.state not in ("submitted", "pending_approval"):
            raise ValidationError(
                _("Requisition is not in a rejectable state.")
            )
        hold_entries = self.env["nn.fund.ledger"].search(
            [
                ("reference_model", "=", self._name),
                ("reference_id", "=", self.id),
                ("transaction_type", "=", "requisition_hold"),
                ("state", "=", "posted"),
            ]
        )
        for hold in hold_entries:
            self.env["nn.fund.ledger"].create(
                {
                    "date": fields.Datetime.now(),
                    "reference": self.reference + "-REL",
                    "transaction_type": "requisition_release",
                    "fund_account_id": hold.fund_account_id.id,
                    "project_id": self.project_id.id,
                    "expense_head_id": self.expense_head_id.id,
                    "reference_model": self._name,
                    "reference_id": self.id,
                    "debit": self.amount,
                    "credit": 0.0,
                    "note": "Release hold for rejected requisition %s" % self.reference,
                    "state": "posted",
                    "company_id": self.company_id.id,
                }
            )
        self.write({
            "state": "rejected",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self.message_post(
            subject=_("Requisition %s Rejected") % self.reference,
            body=_("Requisition %s for %s has been rejected.")
            % (self.reference, self.amount),
        )
        self._notify_requester(
            _("Requisition %s Rejected") % self.reference,
            _("Your requisition %s for %s has been rejected.")
            % (self.reference, self.amount),
        )

    def action_cancel(self):
        self.ensure_one()
        if self.state in ("approved", "rejected", "cancelled", "closed"):
            raise ValidationError(
                _("Cannot cancel requisition in current state.")
            )
        if self.state in ("submitted", "pending_approval"):
            hold_entries = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", self.id),
                    ("transaction_type", "=", "requisition_hold"),
                    ("state", "=", "posted"),
                ]
            )
            for hold in hold_entries:
                self.env["nn.fund.ledger"].create(
                    {
                        "date": fields.Datetime.now(),
                        "reference": self.reference + "-REL",
                        "transaction_type": "requisition_release",
                        "fund_account_id": hold.fund_account_id.id,
                        "project_id": self.project_id.id,
                        "expense_head_id": self.expense_head_id.id,
                        "reference_model": self._name,
                        "reference_id": self.id,
                        "debit": self.amount,
                        "credit": 0.0,
                        "note": "Release hold for cancelled requisition %s" % self.reference,
                        "state": "posted",
                        "company_id": self.company_id.id,
                    }
                )
        self.write({
            "state": "cancelled",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self.message_post(
            subject=_("Requisition %s Cancelled") % self.reference,
            body=_("Requisition %s for %s has been cancelled.")
            % (self.reference, self.amount),
        )
        self._notify_requester(
            _("Requisition %s Cancelled") % self.reference,
            _("Your requisition %s for %s has been cancelled.")
            % (self.reference, self.amount),
        )

    def action_close(self):
        self.ensure_one()
        if self.state != "approved":
            raise ValidationError(
                _("Only approved requisitions can be closed.")
            )
        remaining = self.remaining_billable_amount
        if remaining > 0:
            self.env["nn.fund.ledger"].create(
                {
                    "date": fields.Datetime.now(),
                    "reference": self.reference + "-REL-CLOSE",
                    "transaction_type": "requisition_release",
                    "fund_account_id": self.fund_account_id.id,
                    "project_id": self.project_id.id,
                    "expense_head_id": self.expense_head_id.id,
                    "reference_model": self._name,
                    "reference_id": self.id,
                    "debit": remaining,
                    "credit": 0.0,
                    "note": "Release remaining funds on close of requisition %s" % self.reference,
                    "state": "posted",
                    "company_id": self.company_id.id,
                }
            )
            self.write({
                "state": "closed",
                "released_amount": self.released_amount + remaining,
            })
        else:
            self.write({"state": "closed"})

    @api.model
    def cron_alert_near_exhaustion(self):
        _logger = logging.getLogger(__name__)
        _logger.info("Starting near-exhaustion alert cron")
        approved = self.search([("state", "=", "approved")])
        alerted = 0
        for req in approved:
            if req.approved_amount <= 0:
                continue
            ratio = req.remaining_billable_amount / req.approved_amount
            if ratio < 0.10:
                subject = _("Requisition %s Near Exhaustion") % req.reference
                message = _(
                    "Requisition %(ref)s is nearly exhausted.\n"
                    "Approved: %(approved)s\n"
                    "Remaining: %(remaining)s (%(ratio)s%%)\n"
                    "Please take appropriate action."
                ) % {
                    "ref": req.reference,
                    "approved": req.approved_amount,
                    "remaining": req.remaining_billable_amount,
                    "ratio": round(ratio * 100, 1),
                }
                req._notify_requester(subject, message)
                req.message_post(subject=subject, body=message)
                alerted += 1
        _logger.info(
            "Near-exhaustion alert complete: %d/%d requisitions alerted",
            alerted, len(approved),
        )
        return True
