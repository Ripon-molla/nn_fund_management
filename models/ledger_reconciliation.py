from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class LedgerReconciliation(models.Model):
    _name = "nn.ledger.reconciliation"
    _description = "Ledger Reconciliation"
    _order = "date DESC, id DESC"
    _rec_name = "display_name"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]

    display_name = fields.Char(
        string="Reconciliation",
        compute="_compute_display_name",
        store=True,
    )

    date = fields.Date(
        string="Reconciliation Date",
        required=True,
        default=fields.Date.today,
        index=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        string="State",
        required=True,
        default="draft",
        index=True,
        tracking=True,
    )

    started_by = fields.Many2one(
        comodel_name="res.users",
        string="Started By",
        default=lambda self: self.env.user,
        readonly=True,
    )

    started_at = fields.Datetime(
        string="Started At",
        readonly=True,
    )

    completed_at = fields.Datetime(
        string="Completed At",
        readonly=True,
    )

    duration_seconds = fields.Integer(
        string="Duration (s)",
        compute="_compute_duration",
        store=True,
    )

    total_accounts = fields.Integer(
        string="Accounts Checked",
        default=0,
        readonly=True,
    )

    accounts_with_issues = fields.Integer(
        string="Accounts with Issues",
        default=0,
        readonly=True,
    )

    severity = fields.Selection(
        selection=[
            ("ok", "OK"),
            ("warning", "Warning"),
            ("critical", "Critical"),
        ],
        string="Severity",
        default="ok",
        readonly=True,
        tracking=True,
    )

    block_operations = fields.Boolean(
        string="Block Operations",
        default=False,
        readonly=True,
        help="If True, financial operations are blocked until reconciliation is resolved.",
    )

    summary_html = fields.Html(
        string="Summary Report",
        readonly=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    line_ids = fields.One2many(
        comodel_name="nn.ledger.reconciliation.line",
        inverse_name="reconciliation_id",
        string="Reconciliation Lines",
        readonly=True,
    )

    issue_summary = fields.Text(
        string="Issue Summary",
        compute="_compute_issue_summary",
    )

    _sql_constraints = [
        (
            "unique_date_per_company",
            "UNIQUE(date, company_id)",
            "Only one reconciliation per date per company.",
        ),
    ]

    @api.depends("date", "state")
    def _compute_display_name(self):
        for record in self:
            record.display_name = (
                f"Reconciliation {record.date} [{dict(record._fields['state'].selection).get(record.state, record.state)}]"
            )

    @api.depends("started_at", "completed_at")
    def _compute_duration(self):
        for record in self:
            if record.started_at and record.completed_at:
                delta = record.completed_at - record.started_at
                record.duration_seconds = int(delta.total_seconds())
            else:
                record.duration_seconds = 0

    @api.depends("line_ids")
    def _compute_issue_summary(self):
        for record in self:
            if not record.line_ids:
                record.issue_summary = False
                continue
            critical = record.line_ids.filtered(lambda l: l.severity == "critical")
            warnings = record.line_ids.filtered(lambda l: l.severity == "warning")
            ok_lines = record.line_ids.filtered(lambda l: l.severity == "ok")
            parts = []
            if critical:
                parts.append(_("Critical: %d accounts") % len(critical))
            if warnings:
                parts.append(_("Warnings: %d accounts") % len(warnings))
            parts.append(_("OK: %d accounts") % len(ok_lines))
            record.issue_summary = ", ".join(parts)

    def action_run_reconciliation(self):
        self.ensure_one()
        if self.state not in ("draft", "failed"):
            raise UserError(_("Reconciliation must be in Draft or Failed state to run."))
        self.write({
            "state": "in_progress",
            "started_at": fields.Datetime.now(),
            "completed_at": False,
            "total_accounts": 0,
            "accounts_with_issues": 0,
            "severity": "ok",
            "block_operations": False,
            "summary_html": False,
        })
        self.line_ids.unlink()
        try:
            self._run_checks()
        except Exception as e:
            self.write({
                "state": "failed",
                "completed_at": fields.Datetime.now(),
                "summary_html": f"<h3>Reconciliation Failed</h3><p>{str(e)}</p>",
            })
            self._log_audit("reconcile_failed", description=str(e))
            raise

        self._finalize_reconciliation()
        return True

    def _run_checks(self):
        self.ensure_one()
        accounts = self.env["nn.fund.account"].search(
            [("company_id", "=", self.company_id.id)]
        )
        issue_count = 0
        for account in accounts:
            line_issues = self._check_account(account)
            if line_issues > 0:
                issue_count += line_issues
        self.total_accounts = len(accounts)
        self.accounts_with_issues = issue_count

    def _check_account(self, account):
        self.ensure_one()
        issues = 0
        line_vals = {
            "reconciliation_id": self.id,
            "fund_account_id": account.id,
            "stored_current_balance": account.current_balance,
            "stored_held_balance": account.held_balance,
            "stored_assigned_balance": account.assigned_balance,
            "stored_available_balance": account.available_balance,
            "stored_spent_balance": account.spent_balance,
            "negative_balance": False,
            "has_discrepancy": False,
            "severity": "ok",
        }
        notes = []
        code = account.code

        # 1. Independent ledger-derived computation (bypass stored computed fields)
        ledger = self.env["nn.fund.ledger"]
        posted = ledger.search([
            ("fund_account_id", "=", account.id),
            ("state", "=", "posted"),
        ])
        all_debits = sum(posted.mapped("debit"))
        all_credits = sum(posted.mapped("credit"))
        ledger_current = all_debits - all_credits
        line_vals["ledger_derived_current_balance"] = ledger_current

        aggregates = posted.read_group(
            [("id", "in", posted.ids)],
            ["transaction_type", "debit:sum", "credit:sum"],
            ["transaction_type"],
        )
        type_totals = {}
        for agg in aggregates:
            type_totals[agg["transaction_type"]] = {
                "debit": agg["debit"] or 0.0,
                "credit": agg["credit"] or 0.0,
            }

        incoming_total = type_totals.get("incoming", {}).get("debit", 0.0)
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

        ledger_held = max(0.0, allocation_hold + transfer_hold + requisition_hold
                          - allocation_release - transfer_release - requisition_release)
        ledger_assigned = allocation_approve + transfer_approve
        ledger_spent = max(0.0, bill_post - bill_reversal)
        ledger_available = max(0.0, incoming_total + transfer_approved_in
                               - ledger_held - ledger_assigned - ledger_spent
                               - transfer_approved_out - requisition_approved)

        line_vals["ledger_derived_held_balance"] = ledger_held
        line_vals["ledger_derived_assigned_balance"] = ledger_assigned
        line_vals["ledger_derived_available_balance"] = ledger_available
        line_vals["ledger_derived_spent_balance"] = ledger_spent

        # 2. Compare stored vs ledger-derived
        balance_fields = [
            ("current_balance", "Current Balance"),
            ("held_balance", "Held Balance"),
            ("assigned_balance", "Assigned Balance"),
            ("available_balance", "Available Balance"),
            ("spent_balance", "Spent Balance"),
        ]
        for field_key, field_label in balance_fields:
            stored = line_vals.get("stored_%s" % field_key, 0.0)
            derived = line_vals.get("ledger_derived_%s" % field_key, 0.0)
            if abs(stored - derived) > 0.001:
                notes.append(
                    _("[%s] %s mismatch: stored=%.2f, derived=%.2f (diff=%.2f)")
                    % (code, field_label, stored, derived, stored - derived)
                )
                line_vals["has_discrepancy"] = True

        # 3. Negative balance check
        if ledger_current < -0.001:
            notes.append(
                _("[%s] Negative current balance: %.2f") % (code, ledger_current)
            )
            line_vals["negative_balance"] = True
            line_vals["has_discrepancy"] = True

        # 4. Duplicate ledger entries
        dupes = self._find_duplicate_entries(posted)
        if dupes:
            line_vals["duplicate_count"] = len(dupes)
            notes.append(
                _("[%s] %d duplicate ledger entries found.") % (code, len(dupes))
            )
            line_vals["has_discrepancy"] = True
        else:
            line_vals["duplicate_count"] = 0

        # 5. Missing expected ledger entries
        missing = self._find_missing_entries(account)
        if missing:
            line_vals["missing_entry_count"] = len(missing)
            notes.append(
                _("[%s] %d expected ledger entries missing.") % (code, len(missing))
            )
            line_vals["has_discrepancy"] = True
        else:
            line_vals["missing_entry_count"] = 0

        # 6. Orphan transactions
        orphans = self._find_orphan_entries(posted)
        if orphans:
            line_vals["orphan_count"] = len(orphans)
            notes.append(
                _("[%s] %d orphan ledger entries (deleted source).") % (code, len(orphans))
            )
            line_vals["has_discrepancy"] = True
        else:
            line_vals["orphan_count"] = 0

        # Determine severity
        total_issues = len(dupes) + len(missing) + len(orphans) + (1 if line_vals["has_discrepancy"] else 0)
        if line_vals["negative_balance"]:
            line_vals["severity"] = "critical"
            issues += 1
        elif total_issues > 0:
            line_vals["severity"] = "warning"
            issues += 1
        else:
            line_vals["severity"] = "ok"

        line_vals["notes"] = "\n".join(notes) if notes else False
        self.env["nn.ledger.reconciliation.line"].create(line_vals)
        return issues

    def _find_duplicate_entries(self, posted_entries):
        self.ensure_one()
        dupes = self.env["nn.fund.ledger"]
        seen = {}
        for entry in posted_entries.sorted("id"):
            key = (
                entry.reference,
                entry.transaction_type,
                entry.fund_account_id.id,
                round(entry.debit, 2),
                round(entry.credit, 2),
            )
            if key in seen:
                dupes |= entry
            else:
                seen[key] = entry.id
        return dupes

    def _find_missing_entries(self, account):
        self.ensure_one()
        missing = []
        ref_models = [
            ("nn.fund.allocation", "allocation_hold"),
            ("nn.fund.allocation", "allocation_release"),
            ("nn.fund.allocation", "allocation_approve"),
            ("nn.fund.requisition", "requisition_hold"),
            ("nn.fund.requisition", "requisition_release"),
            ("nn.fund.requisition", "requisition_approved"),
            ("nn.fund.transfer", "transfer_hold"),
            ("nn.fund.transfer", "transfer_release"),
            ("nn.fund.transfer", "transfer_approved_out"),
            ("nn.fund.transfer", "transfer_approved_in"),
        ]
        for model_name, ttype in ref_models:
            Model = self.env.get(model_name)
            if not Model:
                continue
            records = Model.search([
                ("fund_account_id", "=", account.id)
                if model_name != "nn.fund.transfer"
                else ("source_fund_account_id", "=", account.id),
                ("state", "in", ["approved", "submitted", "pending_approval"]),
            ])
            for rec in records:
                exists = self.env["nn.fund.ledger"].search_count([
                    ("reference_model", "=", model_name),
                    ("reference_id", "=", rec.id),
                    ("transaction_type", "=", ttype),
                    ("state", "=", "posted"),
                ], limit=1)
                if not exists:
                    missing.append({
                        "model": model_name,
                        "id": rec.id,
                        "reference": rec.display_name
                        if hasattr(rec, "display_name")
                        else str(rec.id),
                        "expected_type": ttype,
                    })
        return missing

    def _find_orphan_entries(self, posted_entries):
        self.ensure_one()
        orphans = self.env["nn.fund.ledger"]
        for entry in posted_entries:
            model = self.env.get(entry.reference_model)
            if not model:
                continue
            record = model.browse(entry.reference_id)
            if not record.exists():
                orphans |= entry
        return orphans

    def _finalize_reconciliation(self):
        self.ensure_one()
        lines = self.line_ids

        # Calculate overall severity
        if lines.filtered(lambda l: l.severity == "critical"):
            severity = "critical"
        elif lines.filtered(lambda l: l.severity == "warning"):
            severity = "warning"
        else:
            severity = "ok"

        block_ops = bool(lines.filtered(lambda l: l.severity == "critical"))

        # Generate HTML report
        total_ok = len(lines.filtered(lambda l: l.severity == "ok"))
        total_warn = len(lines.filtered(lambda l: l.severity == "warning"))
        total_crit = len(lines.filtered(lambda l: l.severity == "critical"))
        total_issues = lines.filtered(lambda l: l.has_discrepancy)

        report_parts = [
            "<h2>Ledger Reconciliation Report</h2>",
            "<table border='1' cellpadding='4' style='border-collapse:collapse;width:100%'>",
            "<tr style='background:#f0f0f0'>",
            "<th>Account</th><th>Stored Balance</th><th>Derived Balance</th>",
            "<th>Diff</th><th>Dupes</th><th>Missing</th><th>Orphans</th><th>Status</th></tr>",
        ]
        for line in lines:
            diff = line.stored_current_balance - line.ledger_derived_current_balance
            color = "#ffe0e0" if line.severity == "critical" else (
                "#fff8e0" if line.severity == "warning" else "inherit"
            )
            report_parts.append(
                "<tr style='background:%s'>"
                "<td>%s</td><td>%.2f</td><td>%.2f</td><td>%.2f</td>"
                "<td>%d</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                % (
                    color,
                    line.fund_account_id.display_name,
                    line.stored_current_balance,
                    line.ledger_derived_current_balance,
                    diff,
                    line.duplicate_count,
                    line.missing_entry_count,
                    line.orphan_count,
                    dict(line._fields["severity"].selection).get(line.severity, line.severity),
                )
            )
        report_parts.append("</table>")

        # Issue details
        issue_lines = lines.filtered(lambda l: l.notes)
        if issue_lines:
            report_parts.append("<h3>Issue Details</h3>")
            for line in issue_lines:
                report_parts.append(
                    "<h4>%s</h4><pre>%s</pre>"
                    % (line.fund_account_id.display_name, line.notes)
                )

        # Summary
        report_parts.append(
            "<h3>Summary</h3>"
            "<p>Total accounts: %d | OK: %d | Warnings: %d | Critical: %d</p>"
            % (len(lines), total_ok, total_warn, total_crit)
        )
        if block_ops:
            report_parts.append(
                "<p style='color:red;font-weight:bold'>"
                "CRITICAL: Financial operations blocked until resolved.</p>"
            )

        self.write({
            "state": "completed",
            "completed_at": fields.Datetime.now(),
            "total_accounts": len(lines),
            "accounts_with_issues": len(total_issues),
            "severity": severity,
            "block_operations": block_ops,
            "summary_html": "".join(report_parts),
        })

        # Generate alerts
        if block_ops:
            self._generate_alerts("critical")
        elif total_warn > 0:
            self._generate_alerts("warning")

        # Audit log
        self._log_audit(
            "reconcile",
            description="Reconciliation %s completed: %s"
            % (self.date, self.issue_summary or "No issues"),
        )

    def _generate_alerts(self, severity):
        self.ensure_one()
        if severity == "critical":
            admin_group = self.env.ref(
                "nn_fund_management.group_fund_administrator", raise_if_not_found=False
            )
            if admin_group:
                for user in admin_group.users:
                    self.activity_schedule(
                        "mail.mail_activity_data_todo",
                        summary=_("CRITICAL: Financial Operations Blocked"),
                        note=_(
                            "Reconciliation %(date)s detected severe imbalance. "
                            "Financial operations are blocked until resolved.\n\n"
                            "Please review the reconciliation report and correct "
                            "the issues immediately."
                        ) % {"date": self.date},
                        user_id=user.id,
                    )
        elif severity == "warning":
            finance_group = self.env.ref(
                "nn_fund_management.group_finance_user", raise_if_not_found=False
            )
            if finance_group:
                for user in finance_group.users:
                    self.activity_schedule(
                        "mail.mail_activity_data_todo",
                        summary=_("Reconciliation Warnings"),
                        note=_(
                            "Reconciliation %(date)s found %(count)d accounts "
                            "with issues. Please review."
                        ) % {"date": self.date, "count": self.accounts_with_issues},
                        user_id=user.id,
                    )

    def _log_audit(self, action, description=None):
        self.ensure_one()
        self.env["nn.audit.log"]._log(
            model=self._name,
            res_id=self.id,
            action=action,
            reference="RECON-%s" % self.date,
            previous_state=False,
            new_state=self.state,
            description=description
            or "Reconciliation %s: %s" % (self.date, self.state),
        )

    @api.model
    def cron_nightly_reconciliation(self):
        """Cron job: find or create a reconciliation record for today and run it."""
        today = fields.Date.today()
        company = self.env.company
        existing = self.search([
            ("date", "=", today),
            ("company_id", "=", company.id),
            ("state", "in", ("draft", "failed")),
        ], limit=1)
        if existing:
            reconciliation = existing
        else:
            reconciliation = self.create({
                "date": today,
                "company_id": company.id,
            })
        reconciliation.action_run_reconciliation()
        return True

    def action_view_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reconciliation Lines"),
            "res_model": "nn.ledger.reconciliation.line",
            "view_mode": "list,form",
            "domain": [("reconciliation_id", "=", self.id)],
            "context": {"default_reconciliation_id": self.id},
        }

    def action_unblock_operations(self):
        self.ensure_one()
        if not self.env.user.has_group("nn_fund_management.group_fund_administrator"):
            raise UserError(
                _("Only Fund Administrators can unblock operations.")
            )
        if not self.block_operations:
            raise UserError(_("Operations are not currently blocked."))
        self.write({"block_operations": False})
        self._log_audit("unblock", description="Operations unblocked by %s" % self.env.user.name)
        self.message_post(
            subject=_("Operations Unblocked"),
            body=_(
                "Financial operations have been unblocked by %(user)s."
            ) % {"user": self.env.user.name},
        )


class LedgerReconciliationLine(models.Model):
    _name = "nn.ledger.reconciliation.line"
    _description = "Ledger Reconciliation Line"
    _order = "severity DESC, fund_account_id"
    _rec_name = "fund_account_id"

    reconciliation_id = fields.Many2one(
        comodel_name="nn.ledger.reconciliation",
        string="Reconciliation",
        required=True,
        ondelete="cascade",
        index=True,
    )

    fund_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Fund Account",
        required=True,
        index=True,
    )

    stored_current_balance = fields.Monetary(
        string="Stored Current Balance",
        currency_field="currency_id",
    )

    ledger_derived_current_balance = fields.Monetary(
        string="Derived Current Balance",
        currency_field="currency_id",
    )

    stored_held_balance = fields.Monetary(
        string="Stored Held Balance",
        currency_field="currency_id",
    )

    ledger_derived_held_balance = fields.Monetary(
        string="Derived Held Balance",
        currency_field="currency_id",
    )

    stored_assigned_balance = fields.Monetary(
        string="Stored Assigned Balance",
        currency_field="currency_id",
    )

    ledger_derived_assigned_balance = fields.Monetary(
        string="Derived Assigned Balance",
        currency_field="currency_id",
    )

    stored_available_balance = fields.Monetary(
        string="Stored Available Balance",
        currency_field="currency_id",
    )

    ledger_derived_available_balance = fields.Monetary(
        string="Derived Available Balance",
        currency_field="currency_id",
    )

    stored_spent_balance = fields.Monetary(
        string="Stored Spent Balance",
        currency_field="currency_id",
    )

    ledger_derived_spent_balance = fields.Monetary(
        string="Derived Spent Balance",
        currency_field="currency_id",
    )

    duplicate_count = fields.Integer(
        string="Duplicate Entries",
        default=0,
    )

    missing_entry_count = fields.Integer(
        string="Missing Entries",
        default=0,
    )

    orphan_count = fields.Integer(
        string="Orphan Entries",
        default=0,
    )

    negative_balance = fields.Boolean(
        string="Negative Balance",
        default=False,
    )

    has_discrepancy = fields.Boolean(
        string="Has Discrepancy",
        default=False,
    )

    severity = fields.Selection(
        selection=[
            ("ok", "OK"),
            ("warning", "Warning"),
            ("critical", "Critical"),
        ],
        string="Severity",
        default="ok",
    )

    notes = fields.Text(
        string="Notes",
        readonly=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="reconciliation_id.company_id",
        store=True,
        index=True,
    )

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        related="fund_account_id.currency_id",
        store=True,
    )
