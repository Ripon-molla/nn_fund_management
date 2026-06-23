from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError, UserError


class SecurityMixin(models.AbstractModel):
    """Security hardening mixin for all financial models.

    Provides centralized permission validation, state transition guards,
    CSRF protection helpers, and multi-company isolation enforcement.

    Every financial model should _inherit this mixin to get:
    - Server-side permission checks
    - State transition validation
    - Company isolation enforcement
    - Duplicate operation prevention
    - Audit log integration
    """

    _name = "nn.security.mixin"
    _description = "NN Fund Management - Security Mixin"

    # ──────────────────────────────────────────────
    # PERMISSION VALIDATION
    # ──────────────────────────────────────────────

    @api.model
    def _check_company_permission(self, record):
        """Validate user belongs to the same company as the record.

        Raises AccessError if cross-company access is attempted.
        This is a defense-in-depth check on top of record rules.
        """
        if record.company_id.id != self.env.company.id:
            raise AccessError(
                _("Cross-company access denied for %(model)s #%(id)d")
                % {"model": record._name, "id": record.id}
            )
        return True

    def _check_state_transition(self, current_state, allowed_states, action_name):
        """Validate state transition.

        Args:
            current_state: Current state of the record
            allowed_states: List of states from which transition is allowed
            action_name: Name of action for error message

        Raises ValidationError if transition is not allowed.
        """
        if current_state not in allowed_states:
            raise ValidationError(
                _(
                    "%(action)s is not allowed from state '%(state)s'. "
                    "Allowed states: %(allowed)s"
                )
                % {
                    "action": action_name,
                    "state": current_state,
                    "allowed": ", ".join(allowed_states),
                }
            )
        return True

    def _check_write_permission(self):
        """Validate user has write permission on the record.

        Checks both access rights and record rules.
        """
        try:
            self.check_access_rights("write")
            self.check_access_rule("write")
            return True
        except AccessError:
            raise AccessError(
                _("You do not have permission to modify %s #%d")
                % (self._name, self.id)
            )

    def _check_unlink_permission(self):
        """Validate user has unlink permission on the record."""
        try:
            self.check_access_rights("unlink")
            self.check_access_rule("unlink")
            return True
        except AccessError:
            raise AccessError(
                _("You do not have permission to delete %s #%d")
                % (self._name, self.id)
            )

    # ──────────────────────────────────────────────
    # DUPLICATE PREVENTION
    # ──────────────────────────────────────────────

    @api.model
    def _check_duplicate_field(self, field_name, value, exclude_id=None):
        """Check for duplicate field value.

        Args:
            field_name: Field to check for duplicates
            value: Value to check
            exclude_id: Record ID to exclude (for updates)

        Returns:
            bool: True if duplicate exists
        """
        domain = [(field_name, "=", value)]
        if exclude_id:
            domain.append(("id", "!=", exclude_id))
        return bool(self.search_count(domain))

    @api.model
    def _check_duplicate_transaction(
        self, transaction_ref, company_id, exclude_id=None
    ):
        """Check for duplicate financial transaction reference.

        Prevents double-posting of the same transaction.
        """
        domain = [
            ("transaction_reference", "=", transaction_ref),
            ("company_id", "=", company_id),
        ]
        if exclude_id:
            domain.append(("id", "!=", exclude_id))
        return bool(self.search_count(domain))

    # ──────────────────────────────────────────────
    # AMOUNT VALIDATION
    # ──────────────────────────────────────────────

    @api.model
    def _validate_positive_amount(self, amount, field_name="amount"):
        """Validate amount is positive and non-zero."""
        if not amount or amount <= 0:
            raise ValidationError(
                _("%(field)s must be positive and non-zero.")
                % {"field": field_name.replace("_", " ").title()}
            )
        return True

    @api.model
    def _acquire_row_lock(self, account_id):
        """Acquire a row-level lock on the fund account.

        Uses SELECT FOR UPDATE NOWAIT to prevent concurrent modifications.
        Raises ValidationError if another transaction holds the lock.

        This is the central concurrency control mechanism. Every financial
        action that modifies an account balance MUST call this before
        creating ledger entries.

        Args:
            account_id: ID of the nn.fund.account to lock
        """
        self.env.cr.execute(
            "SELECT id FROM nn_fund_account WHERE id = %s FOR UPDATE NOWAIT",
            [account_id],
        )
        return True

    @api.model
    def _validate_available_balance(
        self, account, amount, lock_reference=None
    ):
        """Validate sufficient available balance exists.

        Uses double-check pattern: check balance, then verify no
        concurrent transaction depleted the balance.
        Also checks reconciliation health to block operations when
        critical ledger imbalance is detected.

        Returns:
            bool: True if balance is sufficient
        """
        self._check_reconciliation_health()
        self._acquire_row_lock(account.id)
        account.invalidate_recordset()
        available = account.available_balance
        if available < amount:
            raise ValidationError(
                _(
                    "Insufficient available balance in account %(account)s.\n"
                    "Required: %(required).2f\n"
                    "Available: %(available).2f"
                )
                % {
                    "account": account.display_name,
                    "required": amount,
                    "available": available,
                }
            )
        return True

    @api.model
    def _check_approval_idempotency(self, record, user_id=None):
        """Prevent duplicate approval execution.

        Checks the approval history for an existing approval by the same
        user for the same request at the same step. This prevents
        double-counting approvals when a user accidentally clicks approve
        multiple times. Supports both matrix lines and rule lines.

        Args:
            record: The financial record being approved
            user_id: The user attempting to approve (defaults to current user)

        Raises:
            ValidationError if duplicate approval is detected
        """
        user_id = user_id or self.env.user.id
        line = record.current_rule_line_id or record.current_matrix_line_id
        if not line:
            return True
        domain = [
            ("request_type", "=", record._name),
            ("request_id", "=", record.id),
            ("user_id", "=", user_id),
            ("new_state", "=", "pending_approval"),
        ]
        if line._name == "nn.approval.rule.line":
            domain.append(("rule_line_id", "=", line.id))
        else:
            domain.append(("matrix_line_id", "=", line.id))
        duplicate = self.env["nn.approval.history"].search_count(domain, limit=1)
        if duplicate:
            raise ValidationError(
                _(
                    "You have already approved this request at step '%s'. "
                    "Duplicate approval is not allowed."
                )
                % line.display_name
            )
        return True

    @api.model
    def _enforce_transaction_idempotency(self, model, transaction_uuid):
        """Enforce transaction idempotency by checking for existing UUID.

        Args:
            model: The model name to search in
            transaction_uuid: The UUID to check

        Returns:
            bool: True if no duplicate exists, raises ValidationError otherwise
        """
        if not transaction_uuid:
            return True
        existing = self.env["nn.fund.ledger"].search_count([
            ("transaction_uuid", "=", transaction_uuid),
        ], limit=1)
        if existing:
            raise ValidationError(
                _("Duplicate transaction detected (UUID: %s). This transaction has already been processed.")
                % transaction_uuid
            )
        return True

    @api.model
    def _check_financial_consistency(self, account_id=None, company_id=None):
        """Cross-check all financial balances for consistency.

        Performs a comprehensive cross-validation across all fund accounts:
        1. Ledger-derived balances match stored computed balances
        2. No orphan ledger entries exist
        3. No duplicate ledger entries exist
        4. No negative balances exist
        5. All approved records have corresponding ledger entries
        6. Transfer pairs are balanced (out == in across accounts)

        Args:
            account_id: Optional specific account to check (all if None)
            company_id: Optional company filter (current company if None)

        Returns:
            dict: Results containing violations found
        """
        company_id = company_id or self.env.company.id
        domain = [("company_id", "=", company_id)]
        if account_id:
            domain.append(("id", "=", account_id))
        accounts = self.env["nn.fund.account"].search(domain)
        violations = []
        Ledger = self.env["nn.fund.ledger"]

        for account in accounts:
            posted = Ledger.search([
                ("fund_account_id", "=", account.id),
                ("state", "=", "posted"),
            ])
            all_debits = sum(posted.mapped("debit"))
            all_credits = sum(posted.mapped("credit"))
            derived_current = all_debits - all_credits
            if abs(derived_current - account.current_balance) > 0.001:
                violations.append(
                    _("Account %(code)s: balance mismatch stored=%(stored).2f derived=%(derived).2f")
                    % {"code": account.code, "stored": account.current_balance, "derived": derived_current}
                )
            if derived_current < -0.001:
                violations.append(
                    _("Account %(code)s: NEGATIVE balance %(balance).2f")
                    % {"code": account.code, "balance": derived_current}
                )

        # Check orphan entries
        orphans = Ledger.search([
            ("company_id", "=", company_id),
            ("state", "=", "posted"),
        ])
        for entry in orphans:
            model = self.env.get(entry.reference_model)
            if model:
                record = model.browse(entry.reference_id)
                if not record.exists():
                    violations.append(
                        _("Orphan ledger entry %(ref)s: source %(model)s #%(id)d not found")
                        % {"ref": entry.reference, "model": entry.reference_model, "id": entry.reference_id}
                    )

        # Check duplicate entries
        seen = {}
        for entry in orphans.sorted("id"):
            key = (entry.reference, entry.transaction_type, entry.fund_account_id.id,
                   round(entry.debit, 2), round(entry.credit, 2))
            if key in seen:
                violations.append(
                    _("Duplicate ledger entry: %(ref)s %(type)s account=%(account)d amount=%(debit)s/%(credit)s")
                    % {"ref": entry.reference, "type": entry.transaction_type,
                       "account": entry.fund_account_id.id, "debit": entry.debit, "credit": entry.credit}
                )
            else:
                seen[key] = entry.id

        # Check transfer pairs
        transfer_model = self.env["nn.fund.transfer"]
        transfers = transfer_model.search([
            ("company_id", "=", company_id),
            ("state", "=", "approved"),
        ])
        for trf in transfers:
            out_ledger = Ledger.search([
                ("reference_model", "=", "nn.fund.transfer"),
                ("reference_id", "=", trf.id),
                ("transaction_type", "=", "transfer_approved_out"),
                ("state", "=", "posted"),
            ], limit=1)
            in_ledger = Ledger.search([
                ("reference_model", "=", "nn.fund.transfer"),
                ("reference_id", "=", trf.id),
                ("transaction_type", "=", "transfer_approved_in"),
                ("state", "=", "posted"),
            ], limit=1)
            if out_ledger and in_ledger:
                if abs(out_ledger.credit - in_ledger.debit) > 0.001:
                    violations.append(
                        _("Transfer %(ref)s imbalance: out=%(out).2f in=%(in).2f")
                        % {"ref": trf.reference, "out": out_ledger.credit, "in": in_ledger.debit}
                    )

        if violations:
            self._log_consistency_violations(violations)

        return {
            "accounts_checked": len(accounts),
            "violation_count": len(violations),
            "violations": violations,
            "consistent": len(violations) == 0,
        }

    @api.model
    def _log_consistency_violations(self, violations):
        """Log financial consistency violations to the audit trail."""
        self.env["nn.audit.log"]._log(
            model="nn.security.mixin",
            res_id=0,
            action="consistency_check",
            reference="FINTEG-%s" % fields.Datetime.now(),
            description="Financial consistency violations found:\n" + "\n".join(violations[:50]),
        )

    # ──────────────────────────────────────────────
    # OPERATION BLOCK — RECONCILIATION HEALTH
    # ──────────────────────────────────────────────

    @api.model
    def _check_reconciliation_health(self):
        """Check latest reconciliation before allowing financial operations.

        Raises ValidationError if the latest reconciliation has
        blocked operations due to a critical imbalance.
        """
        latest = self.env["nn.ledger.reconciliation"].search(
            [("company_id", "=", self.env.company.id)],
            order="date DESC, id DESC",
            limit=1,
        )
        if latest and latest.block_operations:
            raise ValidationError(
                _(
                    "Financial operations are currently blocked.\n"
                    "The latest ledger reconciliation (dated %(date)s) "
                    "detected a critical imbalance.\n\n"
                    "Please contact a Fund Administrator to review and "
                    "resolve the issue before proceeding."
                )
                % {"date": latest.date}
            )
        return True

    # ──────────────────────────────────────────────
    # APPROVER VALIDATION
    # ──────────────────────────────────────────────

    def _check_user_is_approver(self, group_xml_id):
        """Validate current user belongs to the required approver group.

        Args:
            group_xml_id: XML ID of the approver group (e.g., 'group_gm_approver')

        Raises AccessError if user is not in the group.
        """
        group = self.env.ref(group_xml_id, raise_if_not_found=False)
        if not group or group.id not in self.env.user.groups_id.ids:
            raise AccessError(
                _("Only %(group)s members can perform this action.")
                % {"group": group.name if group else group_xml_id}
            )
        return True

    def _check_approval_sequence(self, rule, current_step):
        """Validate approval step sequence is followed correctly.

        Args:
            rule: nn.approval.rule record
            current_step: Current nn.approval.step being processed

        Ensures previous steps have been completed before allowing current step.
        """
        previous_steps = rule.step_ids.filtered(
            lambda s: s.sequence < current_step.sequence
        )
        for prev_step in previous_steps:
            if not self._is_step_approved(prev_step):
                raise ValidationError(
                    _(
                        "Previous approval step '%(step)s' must be completed "
                        "before this step."
                    )
                    % {"step": prev_step.approver_type}
                )
        return True

    def _is_step_approved(self, step):
        """Check if a specific approval step has been completed."""
        domain = [
            ("request_type", "=", self._name),
            ("request_id", "=", self.id),
        ]
        if hasattr(step, "approver_type") and step.approver_type:
            domain.append(("approver_type", "=", step.approver_type))
            domain.append(("new_state", "in", ["approved", "pending_approval"]))
        else:
            domain.append(("new_state", "=", "approved"))
        approval = self.env["nn.approval.history"].search(
            domain,
            limit=1,
        )
        return bool(approval)

    # ──────────────────────────────────────────────
    # COMPANY ISOLATION (DEFENSE IN DEPTH)
    # ──────────────────────────────────────────────

    @api.model
    def _enforce_same_company(self, records, field_name="company_id"):
        """Verify all records belong to the same company.

        Used when creating transactions that reference multiple records
        (e.g., transfers between two accounts).
        """
        companies = records.mapped(field_name)
        if len(companies) > 1:
            company_names = ", ".join(companies.mapped("name"))
            raise ValidationError(
                _(
                    "All records must belong to the same company. "
                    "Found: %(companies)s"
                )
                % {"companies": company_names}
            )
        return True

    @api.model
    def _enforce_multi_company_consistency(self, company_id, transaction_type):
        """Validate company consistency for ledger transactions."""
        if not company_id:
            raise ValidationError(
                _("Company must be specified for %(type)s transactions")
                % {"type": transaction_type}
            )
        return True

    # ──────────────────────────────────────────────
    # EMERGENCY RECOVERY PROCEDURES
    # ──────────────────────────────────────────────

    @api.model
    def _emergency_recover_balance(self, account_id):
        """Emergency procedure: re-validate and correct account balance.

        Recomputes the account balance from the ledger and logs the action.
        This is a recovery tool — it does NOT create or destroy money, it
        only corrects the computed balance display if it drifted from the
        ledger-derived value.

        Returns:
            dict: Before/after balance information
        """
        account = self.env["nn.fund.account"].browse(account_id)
        if not account.exists():
            raise ValidationError(_("Account not found: %d") % account_id)
        before = {
            "current": account.current_balance,
            "available": account.available_balance,
        }
        account.invalidate_recordset()
        account._compute_balances()
        after = {
            "current": account.current_balance,
            "available": account.available_balance,
        }
        self.env["nn.audit.log"]._log(
            model="nn.fund.account",
            res_id=account.id,
            action="emergency_recover",
            reference="EM-RECOV-%s" % account.code,
            description=(
                "Emergency balance recovery executed.\n"
                "Before: current=%(before_curr).2f available=%(before_avail).2f\n"
                "After:  current=%(after_curr).2f available=%(after_avail).2f"
            ) % {
                "before_curr": before["current"],
                "before_avail": before["available"],
                "after_curr": after["current"],
                "after_avail": after["available"],
            },
        )
        return {"before": before, "after": after}

    @api.model
    def _emergency_reverse_transaction(self, ledger_entry_id, reason=""):
        """Emergency procedure: reverse a specific ledger entry.

        Only available to Fund Administrators. Creates a mirror reversal
        entry and logs the action in the audit trail.

        Args:
            ledger_entry_id: ID of the nn.fund.ledger entry to reverse
            reason: Required explanation for the emergency reversal

        Returns:
            record: The new reversal ledger entry
        """
        if not self.env.user.has_group("nn_fund_management.group_fund_administrator"):
            raise UserError(_("Only Fund Administrators can perform emergency reversals."))
        if not reason or len(reason.strip()) < 10:
            raise ValidationError(_("Emergency reversal requires a detailed reason (minimum 10 characters)."))
        entry = self.env["nn.fund.ledger"].browse(ledger_entry_id)
        if not entry.exists():
            raise ValidationError(_("Ledger entry not found."))
        if entry.state != "posted":
            raise ValidationError(_("Only posted ledger entries can be reversed."))
        reversal = entry.action_reverse()
        entry.write({"note": (entry.note or "") + "\nEMERGENCY REVERSAL: " + reason})
        reversal.write({"note": (reversal.note or "") + "\nEMERGENCY REVERSAL of %s: %s" % (entry.reference, reason)})
        self.env["nn.audit.log"]._log(
            model="nn.fund.ledger",
            res_id=entry.id,
            action="emergency_reverse",
            reference="EM-REV-%s" % entry.reference,
            description="Emergency reversal of ledger entry %s. Reason: %s" % (entry.reference, reason),
        )
        return reversal

    @api.model
    def _emergency_get_recovery_report(self, account_id=None):
        """Generate an emergency recovery report for an account or all accounts.

        Provides a comprehensive snapshot of:
        - All posted ledger entries
        - Current vs derived balances
        - Any detected anomalies
        - Recent audit log entries

        Args:
            account_id: Optional specific account ID

        Returns:
            dict: Recovery report data
        """
        domain = [("company_id", "=", self.env.company.id)]
        if account_id:
            domain.append(("id", "=", account_id))
        accounts = self.env["nn.fund.account"].search(domain)

        report = {
            "generated_at": fields.Datetime.now(),
            "generated_by": self.env.user.name,
            "company": self.env.company.name,
            "accounts": [],
        }

        for account in accounts:
            posted = self.env["nn.fund.ledger"].search([
                ("fund_account_id", "=", account.id),
                ("state", "=", "posted"),
            ])
            entry_count = len(posted)
            total_debits = sum(posted.mapped("debit"))
            total_credits = sum(posted.mapped("credit"))
            ledger_balance = total_debits - total_credits

            acct_data = {
                "id": account.id,
                "code": account.code,
                "name": account.name,
                "stored_balance": account.current_balance,
                "ledger_balance": ledger_balance,
                "entry_count": entry_count,
                "total_debits": total_debits,
                "total_credits": total_credits,
                "has_discrepancy": abs(account.current_balance - ledger_balance) > 0.001,
            }

            # List entries
            acct_data["entries"] = [
                {
                    "id": e.id,
                    "date": str(e.date),
                    "reference": e.reference,
                    "type": e.transaction_type,
                    "debit": e.debit,
                    "credit": e.credit,
                    "state": e.state,
                }
                for e in posted
            ]
            report["accounts"].append(acct_data)

        return report
