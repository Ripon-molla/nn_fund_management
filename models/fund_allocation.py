from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class FundAllocation(models.Model):
    _name = "nn.fund.allocation"
    _description = "Fund Allocation"
    _order = "request_date DESC, id DESC"
    _rec_name = "request_number"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "nn.notification.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    request_number = fields.Char(
        string="Request Number",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
        states={"draft": [("readonly", False)]},
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        required=True,
        tracking=True,
        check_company=True,
        domain=[("active", "=", True), ("is_closed", "=", False)],
    )

    project_id = fields.Many2one(
        comodel_name="nn.project",
        string="Project",
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

    purpose = fields.Text(
        string="Purpose",
        required=True,
        tracking=True,
    )

    request_date = fields.Date(
        string="Request Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    requested_by = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )

    attachment = fields.Binary(
        string="Attachment",
    )

    attachment_filename = fields.Char(
        string="Attachment Filename",
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
        help="The current approval matrix line being processed.",
    )

    current_rule_line_id = fields.Many2one(
        comodel_name="nn.approval.rule.line",
        string="Current Rule Step",
        index=True,
        readonly=True,
        tracking=True,
        help="The current approval rule line being processed.",
    )

    pending_approval_step = fields.Char(
        string="Current Step",
        compute="_compute_pending_approval_step",
        store=False,
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

    ledger_entry_ids = fields.One2many(
        comodel_name="nn.fund.ledger",
        inverse_name="reference_id",
        string="Ledger Entries",
        compute="_compute_ledger_entry_ids",
        readonly=True,
    )

    requisition_ids = fields.One2many(
        comodel_name="nn.fund.requisition",
        inverse_name="allocation_id",
        string="Requisitions",
    )

    approval_history_ids = fields.One2many(
        comodel_name="nn.approval.history",
        inverse_name="request_id",
        string="Approval History",
        compute="_compute_approval_history_ids",
        readonly=True,
    )

    def _compute_ledger_entry_ids(self):
        for record in self:
            record.ledger_entry_ids = self.env["nn.fund.ledger"].search(
                [
                    ("reference_model", "=", self._name),
                    ("reference_id", "=", record.id),
                ]
            )

    def _compute_approval_history_ids(self):
        for record in self:
            record.approval_history_ids = self.env["nn.approval.history"].search(
                [
                    ("request_type", "=", self._name),
                    ("request_id", "=", record.id),
                ]
            )

    _sql_constraints = [
        (
            "amount_positive",
            "CHECK(amount > 0)",
            "Allocation amount must be positive.",
        ),
        (
            "request_number_unique_per_company",
            "UNIQUE(request_number, company_id)",
            "Request number must be unique per company.",
        ),
    ]

    @api.constrains("project_id", "expense_head_id")
    def _check_project_expense(self):
        for record in self:
            if record.expense_head_id and record.project_id:
                if record.expense_head_id.project_id.id != record.project_id.id:
                    raise ValidationError(
                        _(
                            "Expense Head %(head)s does not belong to "
                            "Project %(project)s."
                        )
                        % {
                            "head": record.expense_head_id.display_name,
                            "project": record.project_id.display_name,
                        }
                    )
            elif not record.expense_head_id and not record.project_id:
                raise ValidationError(
                    _(
                        "An allocation request must specify either a Project "
                        "or an Expense Head."
                    )
                )

    @api.onchange("expense_head_id")
    def _onchange_expense_head_id(self):
        if self.expense_head_id:
            self.project_id = self.expense_head_id.project_id

    @api.onchange("project_id")
    def _onchange_project_id(self):
        if self.project_id and not self.expense_head_id:
            pass
        elif self.project_id and self.expense_head_id:
            if self.expense_head_id.project_id.id != self.project_id.id:
                self.expense_head_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("request_number"):
                vals["request_number"] = self._get_next_request_number()
            if vals.get("expense_head_id") and not vals.get("project_id"):
                expense_head = self.env["nn.expense.head"].browse(
                    vals["expense_head_id"]
                )
                if expense_head:
                    vals["project_id"] = expense_head.project_id.id
        records = super().create(vals_list)
        for record in records:
            record._audit_log("create", _("Allocation created"))
        return records

    def _get_next_request_number(self):
        seq = self.env["ir.sequence"].next_by_code("nn.fund.allocation") or "/"
        return seq

    def _audit_log(self, action, description=None):
        self.ensure_one()
        self.env["nn.audit.log"]._log(
            model=self._name,
            res_id=self.id,
            reference=self.request_number,
            action=action,
            amount=self.amount,
            fund_account_id=self.fund_account_id.id,
            project_id=self.project_id.id,
            expense_head_id=self.expense_head_id.id,
            description=description,
        )

    def _get_approval_matrix(self):
        self.ensure_one()
        return self.env["nn.approval.matrix"]._get_applicable_matrix(
            self._name,
            self.amount,
            self.company_id.id,
            project_id=self.project_id.id if self.project_id else None,
            expense_head_id=self.expense_head_id.id if self.expense_head_id else None,
        )

    def _get_current_line(self):
        return self.current_rule_line_id or self.current_matrix_line_id

    def _get_approval_steps(self):
        matrix = self._get_approval_matrix()
        return self.env["nn.approval.matrix"]._get_valid_lines(matrix, self.amount)

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
        self._log_approval_history(
            previous_state, "pending_approval",
            approval_level=level_name,
            matrix_line_id=line.id if line._name != "nn.approval.rule.line" else None,
            rule_line_id=line.id if line._name == "nn.approval.rule.line" else None,
        )
        self._notify_matrix_line_approvers(line)

    def _notify_matrix_line_approvers(self, line):
        self.ensure_one()
        approvers = line._get_approvers()
        for user in approvers:
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Allocation %s Pending %s Approval")
                         % (self.request_number, line.display_name),
                note=_(
                    "Allocation %(ref)s for %(amount)s requires %(step)s approval.\n"
                    "Purpose: %(purpose)s"
                ) % {
                    "ref": self.request_number,
                    "amount": self.amount,
                    "step": line.display_name,
                    "purpose": self.purpose,
                },
                user_id=user.id,
            )

    def _create_ledger_entry(self, transaction_type, debit=0.0, credit=0.0, note=None):
        self.ensure_one()
        return self.env["nn.fund.ledger"].create(
            {
                "date": fields.Datetime.now(),
                "reference": self.request_number,
                "transaction_type": transaction_type,
                "amount": max(debit, credit),
                "fund_account_id": self.fund_account_id.id,
                "project_id": self.project_id.id,
                "expense_head_id": self.expense_head_id.id,
                "reference_model": self._name,
                "reference_id": self.id,
                "debit": debit,
                "credit": credit,
                "note": note or "",
                "state": "posted",
                "company_id": self.company_id.id,
            }
        )

    def _log_approval_history(self, previous_state, new_state, comment=None,
                              approval_level="System", matrix_line_id=None,
                              rule_line_id=None):
        self.ensure_one()
        self.env["nn.approval.history"]._log_approval(
            request_type=self._name,
            request_id=self.id,
            request_reference=self.request_number,
            previous_state=previous_state,
            new_state=new_state,
            amount=self.amount,
            fund_account_id=self.fund_account_id.id,
            project_id=self.project_id.id,
            expense_head_id=self.expense_head_id.id,
            comment=comment,
            approval_level=approval_level,
            matrix_line_id=matrix_line_id,
            rule_line_id=rule_line_id,
        )

    def action_submit(self):
        self.ensure_one()
        if self.state != "draft":
            raise ValidationError(_("Only draft allocations can be submitted."))
        self._validate_available_balance(self.fund_account_id, self.amount)
        self._create_ledger_entry(
            transaction_type="allocation_hold",
            credit=self.amount,
            note=_("Hold for allocation %s") % self.request_number,
        )
        self.write({"state": "submitted"})
        self._log_approval_history("draft", "submitted")
        self._evaluate_approval_workflow()
        return True

    def _evaluate_approval_workflow(self):
        self.ensure_one()
        steps = self._get_approval_steps()
        if not steps:
            self._finalize_approval()
            return
        self._assign_approval_step(steps[0])

    def _finalize_approval(self):
        self.ensure_one()
        previous_state = self.state
        self._create_ledger_entry(
            transaction_type="allocation_release",
            debit=self.amount,
            note=_("Release hold for allocation %s approval") % self.request_number,
        )
        self._create_ledger_entry(
            transaction_type="allocation_approve",
            credit=self.amount,
            note=_("Approved allocation %s") % self.request_number,
        )
        self.write({
            "state": "approved",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self._log_approval_history(previous_state, "approved", approval_level="Auto")
        self.message_post(
            subject=_("Allocation %s Approved") % self.request_number,
            body=_("Allocation %s has been fully approved for %s.")
            % (self.request_number, self.amount),
        )
        self._notify_requester(
            _("Allocation %s Approved") % self.request_number,
            _("Your allocation request %s for %s has been fully approved.")
            % (self.request_number, self.amount),
        )

    def action_approve(self):
        self.ensure_one()
        if self.state != "pending_approval":
            raise ValidationError(
                _("Allocation is not in a pending approval state.")
            )
        self._check_approval_idempotency(self)
        line = self._get_current_line()
        if not line:
            self._finalize_approval()
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
            next_line = steps[current_idx + 1]
            self._assign_approval_step(next_line)
        else:
            self._finalize_approval()
        return True

    def action_reject(self, comment=None):
        self.ensure_one()
        if self.state not in ("submitted", "pending_approval"):
            raise ValidationError(
                _("Allocation is not in a rejectable state.")
            )
        user = self.env.user
        line = self._get_current_line()
        is_approver = line and line._user_can_approve(user)
        is_admin = user.has_group("nn_fund_management.group_fund_administrator")
        if not (is_approver or is_admin):
            raise ValidationError(
                _("Only current-step approvers or administrators can reject allocations.")
            )
        previous_state = self.state
        self._create_ledger_entry(
            transaction_type="allocation_release",
            debit=self.amount,
            note=_("Release hold for rejected allocation %s") % self.request_number,
        )
        self.write({
            "state": "rejected",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self._log_approval_history(previous_state, "rejected", comment=comment)
        self.message_post(
            subject=_("Allocation %s Rejected") % self.request_number,
            body=_("Allocation %s has been rejected.") % self.request_number,
        )
        self._notify_requester(
            _("Allocation %s Rejected") % self.request_number,
            _("Your allocation request %s for %s has been rejected.")
            % (self.request_number, self.amount),
        )
        return True

    def action_cancel(self):
        self.ensure_one()
        if self.state in ("approved", "rejected", "cancelled"):
            raise ValidationError(
                _("Cannot cancel allocation in current state.")
            )
        previous_state = self.state
        if previous_state in ("submitted", "pending_approval"):
            self._create_ledger_entry(
                transaction_type="allocation_release",
                debit=self.amount,
                note=_("Release hold for cancelled allocation %s") % self.request_number,
            )
        self.write({
            "state": "cancelled",
            "current_matrix_line_id": False,
            "current_rule_line_id": False,
        })
        self._log_approval_history(previous_state, "cancelled")
        self._notify_requester(
            _("Allocation %s Cancelled") % self.request_number,
            _("Your allocation request %s for %s has been cancelled.")
            % (self.request_number, self.amount),
        )
        return True

    def action_draft(self):
        self.ensure_one()
        if self.state not in ("cancelled", "rejected"):
            raise ValidationError(
                _("Only cancelled or rejected allocations can be reset to draft.")
            )
        self.write({"state": "draft"})
        return True
