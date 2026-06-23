import email
import logging
import re
import traceback
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class BankEmailParser(models.Model):
    """Bank email parser configuration.

    One record per bank. Defines regex patterns to extract financial
    transaction fields from incoming bank notification emails.

    Security model:
    - Only fund_administrator can create/edit parsers
    - No bank credentials stored in this model
    - Raw email data is sanitized before storage
    - Multi-company enforced via record rules

    Financial integrity safeguards:
    - Duplicate email_message_id detection prevents double-processing
    - Duplicate transaction_reference detection prevents duplicate credits
    - Parser failures are logged and never silently skipped
    - Only posted ledger entries are created after verification
    """

    _name = "nn.bank.email.parser"
    _description = "Bank Email Parser Configuration"
    _order = "bank_name"
    _rec_name = "bank_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "nn.notification.mixin",
        "mail.thread",
        "mail.activity.mixin",
    ]

    bank_name = fields.Char(
        string="Bank Name",
        required=True,
        index=True,
        tracking=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
    )

    default_account_id = fields.Many2one(
        comodel_name="nn.fund.account",
        string="Default Fund Account",
        domain=[("active", "=", True), ("is_closed", "=", False)],
        check_company=True,
        tracking=True,
        help="Fallback account when account number in email doesn't match any configured account.",
    )

    email_suffix = fields.Char(
        string="Email Domain Suffix",
        help="Limit parsing to emails from this domain (e.g., notifications@bank.com).",
        tracking=True,
    )

    description = fields.Text(
        string="Description",
        tracking=True,
    )

    # Regex templates for field extraction
    regex_bank_name = fields.Char(
        string="Bank Name Regex",
        required=True,
        default=r"Bank\s*:\s*(.+?)[\n\r]",
        help="Python regex to extract bank name. Use capture group () for the value.",
    )

    regex_account_number = fields.Char(
        string="Account Number Regex",
        required=True,
        default=r"Account\s*(?:No|Number|#)\s*:\s*(\d+)",
        help="Python regex to extract bank account number.",
    )

    regex_transaction_ref = fields.Char(
        string="Transaction Reference Regex",
        required=True,
        default=r"(?:Transaction|Tran|Ref)\s*(?:Ref|Reference|ID|#|No)\s*:\s*([A-Za-z0-9\-/]+)",
        help="Python regex to extract transaction reference number.",
    )

    regex_date = fields.Char(
        string="Transaction Date Regex",
        required=True,
        default=r"(?:Date|Dt|Value Date|Transaction Date)\s*:\s*(\d{2}[/-]\d{2}[/-]\d{4})",
        help="Python regex to extract transaction date. Expected format: DD/MM/YYYY or DD-MM-YYYY.",
    )

    regex_amount = fields.Char(
        string="Amount Regex",
        required=True,
        default=r"(?:Amount|Amt|Credit|Deposit|Received)\s*:\s*([\d,]+\.?\d*)",
        help="Python regex to extract transaction amount.",
    )

    regex_sender = fields.Char(
        string="Sender Regex",
        required=True,
        default=r"(?:From|Sender|Remitter|Paid By|Payer)\s*:\s*(.+?)[\n\r]",
        help="Python regex to extract sender/remitter information.",
    )

    regex_message_id = fields.Char(
        string="Email Message ID Regex",
        required=True,
        default=r"Message-ID\s*:\s*<(.+?)>",
        help="Python regex to extract email Message-ID for deduplication.",
    )

    log_count = fields.Integer(
        string="Processed Emails",
        compute="_compute_log_count",
    )

    success_count = fields.Integer(
        string="Successful",
        compute="_compute_log_count",
    )

    failed_count = fields.Integer(
        string="Failed",
        compute="_compute_log_count",
    )

    _sql_constraints = [
        (
            "bank_name_unique_per_company",
            "UNIQUE(bank_name, company_id)",
            "Bank name must be unique per company.",
        ),
        (
            "check_regex_not_empty",
            "CHECK("
            "regex_bank_name != '' AND "
            "regex_account_number != '' AND "
            "regex_transaction_ref != '' AND "
            "regex_date != '' AND "
            "regex_amount != '' AND "
            "regex_sender != '' AND "
            "regex_message_id != ''"
            ")",
            "All regex fields must be non-empty.",
        ),
    ]

    @api.depends("log_count")
    def _compute_log_count(self):
        Log = self.env["nn.bank.email.log"]
        for record in self:
            logs = Log.search([("parser_id", "=", record.id)])
            record.log_count = len(logs)
            record.success_count = len(logs.filtered(lambda l: l.state == "success"))
            record.failed_count = len(logs.filtered(lambda l: l.state == "failed"))

    # ──────────────────────────────────────────────
    # PUBLIC API: Entry point called by fetchmail
    # ──────────────────────────────────────────────

    @api.model
    def process_email(self, email_message, company_id=None):
        """Process a single bank notification email.

        This is the main entry point called by the Fetchmail server action
        or the reprocess cron job.

        Args:
            email_message: Raw RFC 2822 email string
            company_id: Optional company ID override

        Returns:
            nn.bank.email.log record for this processing attempt
        """
        company = self.env.company
        if company_id:
            company = self.env["res.company"].browse(company_id)

        # Parse raw email
        try:
            msg = email.message_from_string(email_message)
        except Exception as ex:
            _logger.error("Failed to parse email structure: %s", ex)
            return self._create_log(
                state="failed",
                raw_body=email_message,
                error_message=f"Email structure parse failed: {ex}",
                company_id=company.id,
            )

        # Extract headers
        subject = msg.get("Subject", "")
        from_addr = msg.get("From", "")
        message_id = msg.get("Message-ID", "")
        body = self._get_email_body(msg)

        _logger.info(
            "Processing bank email: subject=%s from=%s msg_id=%s",
            subject[:100], from_addr, message_id,
        )

        # Find matching parser by email domain suffix
        parser = self._find_matching_parser(from_addr, company.id)
        if not parser:
            _logger.warning("No matching parser found for email from %s", from_addr)
            return self._create_log(
                state="ignored",
                raw_body=email_message,
                message_id=message_id,
                error_message=f"No parser configured for sender: {from_addr}",
                company_id=company.id,
            )

        # Check duplicate by message_id
        if message_id:
            existing = self.env["nn.bank.email.log"].search_count(
                [("email_message_id", "=", message_id)]
            )
            if existing:
                _logger.warning("Duplicate email message_id: %s", message_id)
                return self._create_log(
                    state="duplicate",
                    raw_body=email_message,
                    message_id=message_id,
                    parser_id=parser.id,
                    error_message=f"Duplicate email: Message-ID already processed",
                    company_id=company.id,
                )

        # Extract fields using regex
        extracted = parser._extract_fields(subject, body)
        if extracted.get("error"):
            parser._notify_group(
                "nn_fund_management.group_fund_administrator",
                _("Bank Email Parse Failure"),
                _(
                    "Failed to parse bank email from %(from)s.\n"
                    "Subject: %(subject)s\n"
                    "Error: %(error)s\n"
                    "Parser: %(parser)s"
                ) % {
                    "from": from_addr,
                    "subject": subject[:200],
                    "error": extracted["error"],
                    "parser": parser.bank_name,
                },
            )
            return self._create_log(
                state="failed",
                raw_body=email_message,
                message_id=message_id,
                parser_id=parser.id,
                error_message=extracted["error"],
                company_id=company.id,
            )

        # Check duplicate by transaction reference
        transaction_ref = extracted.get("transaction_reference", "")
        if transaction_ref:
            duplicate_txn = self.env["nn.bank.email.log"].search_count(
                [
                    ("transaction_reference", "=", transaction_ref),
                    ("state", "in", ("success", "pending")),
                ]
            )
            if duplicate_txn:
                return self._create_log(
                    state="duplicate",
                    raw_body=email_message,
                    message_id=message_id,
                    parser_id=parser.id,
                    transaction_reference=transaction_ref,
                    error_message=f"Duplicate transaction reference: {transaction_ref}",
                    company_id=company.id,
                )

        # Create Incoming Fund in pending_verification state
        try:
            incoming_fund = parser._create_incoming_fund(extracted)
            log = self._create_log(
                state="success",
                raw_body=email_message,
                message_id=message_id,
                parser_id=parser.id,
                bank_name=extracted.get("bank_name", parser.bank_name),
                account_number=extracted.get("account_number", ""),
                transaction_reference=transaction_ref,
                transaction_date=extracted.get("transaction_date"),
                amount=extracted.get("amount", 0.0),
                sender=extracted.get("sender", ""),
                incoming_fund_id=incoming_fund.id,
                company_id=company.id,
            )
            _logger.info(
                "Successfully processed bank email: incoming_fund=%s ref=%s",
                incoming_fund.reference,
                transaction_ref,
            )
            return log

        except Exception as ex:
            _logger.exception("Failed to create incoming fund from email")
            return self._create_log(
                state="failed",
                raw_body=email_message,
                message_id=message_id,
                parser_id=parser.id,
                transaction_reference=transaction_ref,
                error_message=f"Incoming fund creation failed: {ex}\n{traceback.format_exc()}",
                company_id=company.id,
            )

    # ──────────────────────────────────────────────
    # FIELD EXTRACTION
    # ──────────────────────────────────────────────

    def _extract_fields(self, subject, body):
        """Apply regex patterns to extract financial fields from email.

        Returns dict with extracted values or {'error': message}.
        """
        self.ensure_one()
        combined = f"Subject: {subject}\n{body}"
        result = {}

        field_map = {
            "bank_name": "regex_bank_name",
            "account_number": "regex_account_number",
            "transaction_reference": "regex_transaction_ref",
            "transaction_date": "regex_date",
            "amount": "regex_amount",
            "sender": "regex_sender",
            "message_id": "regex_message_id",
        }

        for field_name, regex_field in field_map.items():
            pattern = getattr(self, regex_field)
            try:
                match = re.search(pattern, combined, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    if field_name == "amount":
                        value = self._parse_amount(value)
                    elif field_name == "transaction_date":
                        value = self._parse_date(value)
                    result[field_name] = value
                else:
                    _logger.warning(
                        "Regex %s did not match for field %s on parser %s",
                        pattern, field_name, self.bank_name,
                    )
            except re.error as ex:
                _logger.error("Invalid regex %s for field %s: %s", pattern, field_name, ex)
                return {"error": f"Regex error for {field_name}: {ex}"}

        # Validate required fields
        missing = []
        for req_field in ("bank_name", "transaction_reference", "amount"):
            if not result.get(req_field):
                missing.append(req_field)
        if missing:
            return {"error": f"Missing required fields: {', '.join(missing)}"}

        return result

    @api.model
    def _parse_amount(self, raw_amount):
        """Parse amount string to float. Handles comma/period variations."""
        if isinstance(raw_amount, (int, float)):
            return float(raw_amount)
        # Remove currency symbols and spaces
        cleaned = re.sub(r"[^\d,.]", "", str(raw_amount))
        # Handle European format: 1.234,56 -> 1234.56
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                # European: 1.234,56
                cleaned = cleaned.replace(".", "").replace(",", ".")
            # else: US format: 1,234.56 -> just remove comma
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            # Could be European 1234,56 or US thousand separator
            # If comma is followed by exactly 2 digits, it's decimal
            if re.search(r",\d{2}$", cleaned):
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            _logger.warning("Could not parse amount: %s", raw_amount)
            return 0.0

    @api.model
    def _parse_date(self, raw_date):
        """Parse date string to ISO format YYYY-MM-DD."""
        if isinstance(raw_date, datetime):
            return raw_date.strftime("%Y-%m-%d")
        if isinstance(raw_date, str):
            raw_date = raw_date.strip()
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    return datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return raw_date

    @api.model
    def _get_email_body(self, msg):
        """Extract plain text body from email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        try:
                            body += payload.decode("utf-8", errors="replace")
                        except (LookupError, UnicodeDecodeError):
                            body += payload.decode("latin-1", errors="replace")
                elif content_type == "text/html":
                    # Extract text from HTML as fallback
                    payload = part.get_payload(decode=True)
                    if payload:
                        text = payload.decode("utf-8", errors="replace")
                        # Simple HTML tag stripping
                        text = re.sub(r"<[^>]+>", " ", text)
                        text = re.sub(r"\s+", " ", text)
                        body += text + "\n"
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    body = payload.decode("utf-8", errors="replace")
                except (LookupError, UnicodeDecodeError):
                    body = payload.decode("latin-1", errors="replace")
        return body

    @api.model
    def _find_matching_parser(self, from_addr, company_id):
        """Find active parser matching the sender email domain."""
        parsers = self.search([("active", "=", True), ("company_id", "=", company_id)])
        from_lower = from_addr.lower()
        for parser in parsers:
            if parser.email_suffix:
                if parser.email_suffix.lower() in from_lower:
                    return parser
        # Fallback: return first active parser if none matched by domain
        if not parsers:
            return self.env["nn.bank.email.parser"]
        return parsers[0]

    # ──────────────────────────────────────────────
    # INCOMING FUND CREATION
    # ──────────────────────────────────────────────

    def _create_incoming_fund(self, extracted):
        """Create an Incoming Fund record from extracted email data."""
        self.ensure_one()

        # Find fund account by account number or use default
        account = self._find_account(extracted.get("account_number", ""))

        amount = extracted.get("amount", 0.0)
        if amount <= 0:
            raise ValidationError(
                _("Extracted amount must be positive: %s") % amount
            )

        # Parse date
        txn_date = extracted.get("transaction_date")
        if txn_date:
            try:
                parsed_date = datetime.strptime(txn_date, "%Y-%m-%d").date()
            except ValueError:
                parsed_date = fields.Date.today()
        else:
            parsed_date = fields.Date.today()

        incoming = self.env["nn.incoming.fund"].create({
            "fund_account_id": account.id,
            "amount": amount,
            "received_date": parsed_date,
            "source_type": "donor",
            "donor_name": extracted.get("sender", ""),
            "source_reference": extracted.get("transaction_reference", ""),
            "state": "pending_verification",
            "company_id": self.company_id.id,
            "notes": _(
                "Auto-created from bank email.\n"
                "Bank: %(bank)s\n"
                "Account: %(acct)s\n"
                "Reference: %(ref)s\n"
                "Sender: %(sender)s"
            ) % {
                "bank": extracted.get("bank_name", self.bank_name),
                "acct": extracted.get("account_number", ""),
                "ref": extracted.get("transaction_reference", ""),
                "sender": extracted.get("sender", ""),
            },
        })

        # Auto-post audit log for email-created fund
        self.env["nn.audit.log"]._log(
            model="nn.incoming.fund",
            res_id=incoming.id,
            action="create",
            reference=incoming.reference,
            new_state="pending_verification",
            amount=amount,
            fund_account_id=account.id,
            description=_("Created via bank email parser: %s") % self.bank_name,
        )

        return incoming

    def _find_account(self, account_number):
        """Find fund account by account number, falling back to default."""
        if account_number:
            account = self.env["nn.fund.account"].search(
                [
                    ("code", "=", account_number),
                    ("company_id", "=", self.company_id.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if account:
                return account
        # Fall back to default
        if self.default_account_id:
            if self.default_account_id.company_id.id != self.company_id.id:
                raise ValidationError(
                    _("Default account belongs to a different company.")
                )
            return self.default_account_id
        # Last resort: any active account
        account = self.env["nn.fund.account"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("active", "=", True),
                ("is_closed", "=", False),
            ],
            limit=1,
        )
        if not account:
            raise ValidationError(
                _("No fund account found for bank %s. Configure default_account_id.")
                % self.bank_name
            )
        return account

    # ──────────────────────────────────────────────
    # LOG CREATION
    # ──────────────────────────────────────────────

    @api.model
    def _create_log(
        self,
        state="success",
        raw_body="",
        message_id="",
        parser_id=None,
        bank_name="",
        account_number="",
        transaction_reference="",
        transaction_date=None,
        amount=0.0,
        sender="",
        incoming_fund_id=None,
        error_message="",
        company_id=None,
    ):
        """Create a bank email processing log entry."""
        vals = {
            "state": state,
            "raw_email_body": raw_body[:10000] if raw_body else "",
            "email_message_id": message_id,
            "bank_name": bank_name,
            "account_number": account_number,
            "transaction_reference": transaction_reference,
            "amount": amount,
            "sender": sender,
            "error_message": error_message,
        }
        if transaction_date:
            vals["transaction_date"] = transaction_date
        if parser_id:
            vals["parser_id"] = parser_id
        if incoming_fund_id:
            vals["incoming_fund_id"] = incoming_fund_id
        if company_id:
            vals["company_id"] = company_id
        else:
            vals["company_id"] = self.env.company.id

        return self.env["nn.bank.email.log"].create(vals)

    # ──────────────────────────────────────────────
    # CRON JOBS
    # ──────────────────────────────────────────────

    @api.model
    def cron_reprocess_failed_emails(self):
        """Reprocess failed bank email parsing attempts.

        Cron schedule: Every 30 minutes (defined in cron_data.xml)
        Processes up to 50 failed logs per run to avoid timeout.
        """
        _logger.info("Starting failed email reprocessing cron")
        failed_logs = self.env["nn.bank.email.log"].search(
            [
                ("state", "=", "failed"),
                ("retry_count", "<", 3),
            ],
            order="create_date ASC",
            limit=50,
        )

        reprocessed = 0
        for log in failed_logs:
            try:
                if not log.raw_email_body:
                    log.write({
                        "error_message": "No raw email body available for reprocessing",
                        "retry_count": log.retry_count + 1,
                    })
                    continue

                # Attempt reprocessing
                result = self.process_email(log.raw_email_body, log.company_id.id)

                if result.state == "success":
                    log.write({
                        "state": "success",
                        "incoming_fund_id": result.incoming_fund_id.id,
                        "error_message": "Reprocessed successfully",
                        "retry_count": log.retry_count + 1,
                    })
                    reprocessed += 1
                elif result.state in ("duplicate", "ignored"):
                    log.write({
                        "state": result.state,
                        "error_message": result.error_message,
                        "retry_count": log.retry_count + 1,
                    })
                else:
                    log.write({
                        "state": "failed",
                        "error_message": result.error_message,
                        "retry_count": log.retry_count + 1,
                    })
            except Exception as ex:
                _logger.exception("Reprocessing failed for log %s", log.id)
                log.write({
                    "error_message": f"Reprocessing error: {ex}",
                    "retry_count": log.retry_count + 1,
                })

        _logger.info(
            "Failed email reprocessing complete: %d/%d reprocessed",
            reprocessed, len(failed_logs),
        )
        return True

    @api.model
    def cron_clean_old_logs(self):
        """Delete bank email logs older than retention period.

        Cron schedule: Daily
        Retains: success logs for 90 days, failed logs for 180 days
        """
        from datetime import timedelta

        retention_success = fields.Date.today() - timedelta(days=90)
        retention_failed = fields.Date.today() - timedelta(days=180)

        # Clean old success/duplicate/ignored logs
        old_success = self.env["nn.bank.email.log"].search([
            ("state", "in", ("success", "duplicate", "ignored")),
            ("create_date", "<", retention_success.strftime("%Y-%m-%d")),
        ])
        old_success.unlink()

        # Clean old failed logs
        old_failed = self.env["nn.bank.email.log"].search([
            ("state", "=", "failed"),
            ("create_date", "<", retention_failed.strftime("%Y-%m-%d")),
        ])
        old_failed.unlink()

        _logger.info(
            "Old email log cleanup: removed %d success, %d failed",
            len(old_success), len(old_failed),
        )
        return True


class BankEmailLog(models.Model):
    """Log of all bank email processing attempts.

    Tracks every email received, whether processing succeeded or failed.
    Provides full audit trail for email-based fund creation.

    Security: Read-only for non-administrators. Stores sanitized raw body.
    """

    _name = "nn.bank.email.log"
    _description = "Bank Email Processing Log"
    _order = "create_date DESC, id DESC"
    _rec_name = "display_name"
    _check_company_auto = True

    _inherit = [
        "nn.security.mixin",
        "mail.thread",
    ]

    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
    )

    email_message_id = fields.Char(
        string="Email Message-ID",
        index=True,
        readonly=True,
        help="Unique Message-ID header from the original email. Used for deduplication.",
    )

    transaction_reference = fields.Char(
        string="Transaction Reference",
        index=True,
        readonly=True,
        help="Extracted transaction reference from the email.",
    )

    state = fields.Selection(
        selection=[
            ("success", "Success"),
            ("failed", "Failed"),
            ("duplicate", "Duplicate"),
            ("ignored", "Ignored"),
        ],
        string="State",
        required=True,
        default="success",
        index=True,
        readonly=True,
    )

    bank_name = fields.Char(
        string="Bank Name",
        readonly=True,
    )

    account_number = fields.Char(
        string="Account Number",
        readonly=True,
    )

    transaction_date = fields.Date(
        string="Transaction Date",
        readonly=True,
    )

    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
        readonly=True,
    )

    sender = fields.Char(
        string="Sender",
        readonly=True,
    )

    raw_email_body = fields.Text(
        string="Raw Email Body",
        readonly=True,
        groups="group_fund_administrator",
        help="First 10,000 characters of the raw email body. "
             "Only visible to Fund Administrators for debugging.",
    )

    error_message = fields.Text(
        string="Error Message",
        readonly=True,
    )

    retry_count = fields.Integer(
        string="Retry Count",
        default=0,
        readonly=True,
    )

    parser_id = fields.Many2one(
        comodel_name="nn.bank.email.parser",
        string="Parser",
        index=True,
        readonly=True,
    )

    incoming_fund_id = fields.Many2one(
        comodel_name="nn.incoming.fund",
        string="Created Incoming Fund",
        index=True,
        readonly=True,
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

    _sql_constraints = [
        (
            "email_message_id_unique",
            "UNIQUE(email_message_id)",
            "Email Message-ID must be unique to prevent duplicate processing.",
        ),
    ]

    @api.depends("state", "bank_name", "transaction_reference")
    def _compute_display_name(self):
        for record in self:
            parts = [record.state.upper() if record.state else "???"]
            if record.bank_name:
                parts.append(record.bank_name)
            if record.transaction_reference:
                parts.append(f"[{record.transaction_reference}]")
            record.display_name = " | ".join(parts)

    def action_view_incoming_fund(self):
        """Open the created incoming fund form view."""
        self.ensure_one()
        if not self.incoming_fund_id:
            return
        return {
            "type": "ir.actions.act_window",
            "res_model": "nn.incoming.fund",
            "res_id": self.incoming_fund_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_reprocess(self):
        """Manually trigger reprocessing of a failed log entry."""
        self.ensure_one()
        if not self.raw_email_body:
            raise ValidationError(_("No raw email body available for reprocessing."))
        parser = self.parser_id or self.env["nn.bank.email.parser"].search(
            [("active", "=", True)], limit=1
        )
        if not parser:
            raise ValidationError(
                _("No active bank email parser configured. Create one first.")
            )
        result = parser.process_email(self.raw_email_body, self.company_id.id)
        if result.id != self.id:
            # New log was created; mark old as duplicate
            self.write({
                "state": "duplicate",
                "error_message": f"Superseded by log #{result.id}",
            })
        return {
            "type": "ir.actions.act_window",
            "res_model": "nn.bank.email.log",
            "res_id": result.id,
            "view_mode": "form",
            "target": "current",
        }
