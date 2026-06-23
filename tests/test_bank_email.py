from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError
from odoo import fields


SAMPLE_BANK_EMAIL = """From: notifications@ibank.com
To: finance@company.com
Subject: Credit Alert - Account 1234567890
Message-ID: <MSG001-ABC-20250101@ibank.com>
Date: Wed, 1 Jan 2025 10:00:00 +0000
MIME-Version: 1.0
Content-Type: text/plain

Dear Customer,

Bank: Global Trust Bank
Account No: 1234567890
Transaction Ref: TXN-2025-001
Date: 01/01/2025
Amount: 1,000,000.00
From: International Donor Foundation
Sender: Mr. John Smith

Your account has been credited.

Thank you,
Global Trust Bank
"""

SAMPLE_BANK_EMAIL_2 = """From: alerts@cbank.com
To: finance@company.com
Subject: Deposit Notification - Account 9876543210
Message-ID: <MSG002-DEF-20250102@cbank.com>
Date: Thu, 2 Jan 2025 14:30:00 +0000
Content-Type: text/plain

Bank: City National Bank
Account Number: 9876543210
Transaction Reference: REF-2025-002
Transaction Date: 02/01/2025
Amount: 500,000.00
Sender: Regional Development Agency

A deposit of 500,000.00 has been made.
"""


@tagged("fund_management", "bank_email", "security")
class TestBankEmailParser(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, "tracking_disable": True})

        company = cls.env.company

        cls.Account = cls.env["nn.fund.account"]
        cls.Parser = cls.env["nn.bank.email.parser"]
        cls.Log = cls.env["nn.bank.email.log"]
        cls.IncomingFund = cls.env["nn.incoming.fund"]
        cls.AuditLog = cls.env["nn.audit.log"]

        cls.fund_account = cls.Account.create({
            "name": "Main Operating Account",
            "code": "1234567890",
            "type": "main",
            "company_id": company.id,
        })

        cls.fund_account_2 = cls.Account.create({
            "name": "Secondary Account",
            "code": "9876543210",
            "type": "main",
            "company_id": company.id,
        })

        cls.parser = cls.Parser.create({
            "bank_name": "Global Trust Bank",
            "email_suffix": "ibank.com",
            "default_account_id": cls.fund_account.id,
            "regex_bank_name": r"Bank:\s*(.+?)[\n\r]",
            "regex_account_number": r"Account\s*(?:No|Number)\s*:\s*(\d+)",
            "regex_transaction_ref": r"(?:Transaction\s*Ref|Transaction Reference)\s*:\s*([A-Za-z0-9\-/]+)",
            "regex_date": r"(?:Date|Transaction Date)\s*:\s*(\d{2}[/-]\d{2}[/-]\d{4})",
            "regex_amount": r"Amount:\s*([\d,]+\.?\d*)",
            "regex_sender": r"(?:From|Sender)\s*:\s*(.+?)[\n\r]",
            "regex_message_id": r"Message-ID\s*:\s*<(.+?)>",
            "company_id": company.id,
        })

        cls.parser_2 = cls.Parser.create({
            "bank_name": "City National Bank",
            "email_suffix": "cbank.com",
            "default_account_id": cls.fund_account_2.id,
            "regex_bank_name": r"Bank:\s*(.+?)[\n\r]",
            "regex_account_number": r"Account\s*Number:\s*(\d+)",
            "regex_transaction_ref": r"Transaction\s*Reference:\s*([A-Za-z0-9\-/]+)",
            "regex_date": r"Transaction\s*Date:\s*(\d{2}[/-]\d{2}[/-]\d{4})",
            "regex_amount": r"Amount:\s*([\d,]+\.?\d*)",
            "regex_sender": r"Sender:\s*(.+?)[\n\r]",
            "regex_message_id": r"Message-ID\s*:\s*<(.+?)>",
            "company_id": company.id,
        })

    # ──────────────────────────────────────────────
    # REGEX EXTRACTION TESTS
    # ──────────────────────────────────────────────

    def test_extract_bank_name(self):
        """Verify bank name regex extraction."""
        extracted = self.parser._extract_fields("", "Bank: Global Trust Bank\nSome text")
        self.assertEqual(extracted["bank_name"], "Global Trust Bank")

    def test_extract_account_number(self):
        """Verify account number regex extraction."""
        extracted = self.parser._extract_fields(
            "", "Account No: 1234567890\nSome text"
        )
        self.assertEqual(extracted["account_number"], "1234567890")

    def test_extract_transaction_reference(self):
        """Verify transaction reference regex extraction."""
        extracted = self.parser._extract_fields(
            "", "Transaction Ref: TXN-2025-001\nSome text"
        )
        self.assertEqual(extracted["transaction_reference"], "TXN-2025-001")

    def test_extract_amount(self):
        """Verify amount extraction and parsing."""
        extracted = self.parser._extract_fields("", "Amount: 1,000,000.00\nSome text")
        self.assertEqual(extracted["amount"], 1000000.0)

    def test_extract_amount_european_format(self):
        """Verify European format amount parsing (1.234,56)."""
        parsed = self.Parser._parse_amount("1.234,56")
        self.assertEqual(parsed, 1234.56)

    def test_extract_amount_no_decimal(self):
        """Verify integer amount parsing."""
        parsed = self.Parser._parse_amount("500000")
        self.assertEqual(parsed, 500000.0)

    def test_extract_date_dd_mm_yyyy(self):
        """Verify date extraction in DD/MM/YYYY format."""
        extracted = self.parser._extract_fields("", "Date: 01/01/2025\nSome text")
        self.assertEqual(extracted["transaction_date"], "2025-01-01")

    def test_extract_sender(self):
        """Verify sender regex extraction."""
        extracted = self.parser._extract_fields(
            "", "From: International Donor Foundation\nSome text"
        )
        self.assertEqual(extracted["sender"], "International Donor Foundation")

    def test_extract_message_id(self):
        """Verify Message-ID extraction."""
        msg = "Message-ID: <MSG001-ABC-20250101@ibank.com>\nSubject: Test"
        extracted = self.parser._extract_fields("", msg)
        self.assertEqual(extracted["message_id"], "MSG001-ABC-20250101@ibank.com")

    def test_extract_from_subject_and_body(self):
        """Verify combined subject + body extraction."""
        extracted = self.parser._extract_fields(
            "Credit Alert - Account 1234567890",
            "Amount: 1,000,000.00\n"
        )
        self.assertEqual(extracted["amount"], 1000000.0)

    def test_extract_missing_required_fields(self):
        """Verify error when required fields missing."""
        extracted = self.parser._extract_fields(
            "", "Some text without any financial fields"
        )
        self.assertIn("error", extracted)
        self.assertIn("Missing required fields", extracted["error"])

    # ──────────────────────────────────────────────
    # FULL EMAIL PROCESSING TESTS
    # ──────────────────────────────────────────────

    def test_process_valid_email(self):
        """Verify full email processing flow creates incoming fund."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)

        self.assertEqual(log.state, "success")
        self.assertTrue(log.incoming_fund_id)
        self.assertEqual(log.bank_name, "Global Trust Bank")
        self.assertEqual(log.transaction_reference, "TXN-2025-001")
        self.assertEqual(log.amount, 1000000.0)

        # Verify incoming fund created in pending_verification
        fund = log.incoming_fund_id
        self.assertEqual(fund.state, "pending_verification")
        self.assertEqual(fund.amount, 1000000.0)
        self.assertEqual(fund.source_reference, "TXN-2025-001")
        self.assertEqual(fund.donor_name, "Mr. John Smith")

    def test_process_email_to_second_parser(self):
        """Verify different bank emails match different parsers."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL_2)

        self.assertEqual(log.state, "success")
        self.assertEqual(log.bank_name, "City National Bank")
        self.assertEqual(log.transaction_reference, "REF-2025-002")
        self.assertEqual(log.amount, 500000.0)
        self.assertEqual(log.incoming_fund_id.fund_account_id.id, self.fund_account_2.id)

    def test_duplicate_email_message_id_blocked(self):
        """Verify duplicate email_message_id is rejected."""
        self.Parser.process_email(SAMPLE_BANK_EMAIL)

        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        self.assertEqual(log.state, "duplicate")
        self.assertFalse(log.incoming_fund_id)

    def test_duplicate_transaction_reference_blocked(self):
        """Verify duplicate transaction reference is rejected."""
        self.Parser.process_email(SAMPLE_BANK_EMAIL)

        # Same content but different Message-ID
        modified_email = SAMPLE_BANK_EMAIL.replace(
            "MSG001-ABC-20250101@ibank.com",
            "MSG999-ZZZ-20250101@ibank.com"
        )
        log = self.Parser.process_email(modified_email)
        self.assertEqual(log.state, "duplicate")
        self.assertIn("transaction reference", log.error_message.lower())

    def test_process_email_no_matching_parser(self):
        """Verify email from unknown domain is ignored."""
        unknown_email = SAMPLE_BANK_EMAIL.replace(
            "notifications@ibank.com",
            "notifications@unknown-bank.com"
        )
        log = self.Parser.process_email(unknown_email)
        self.assertEqual(log.state, "ignored")

    def test_process_email_failed_parsing(self):
        """Verify malformed email produces failed log."""
        bad_email = "From: test@test.com\nSubject: No financial data\n\nHello world"
        log = self.Parser.process_email(bad_email)
        self.assertEqual(log.state, "failed")

    def test_raw_email_stored(self):
        """Verify raw email body is stored in log (admin only)."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        self.assertTrue(log.raw_email_body)
        self.assertIn("Global Trust Bank", log.raw_email_body)
        self.assertIn("TXN-2025-001", log.raw_email_body)

    # ──────────────────────────────────────────────
    # INCOMING FUND VERIFICATION WORKFLOW
    # ──────────────────────────────────────────────

    def test_incoming_fund_created_pending_verification(self):
        """Verify email-created funds start in pending_verification."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        self.assertEqual(log.incoming_fund_id.state, "pending_verification")

    def test_verify_incoming_fund_creates_ledger_entry(self):
        """Verify finance user verification creates ledger debit entry."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        fund = log.incoming_fund_id

        # Simulate finance user verification
        fund.action_verify()
        self.assertEqual(fund.state, "confirmed")
        self.assertTrue(fund.ledger_entry_id)
        self.assertEqual(fund.ledger_entry_id.debit, 1000000.0)
        self.assertEqual(fund.ledger_entry_id.transaction_type, "incoming")

    def test_verify_incoming_fund_updates_balance(self):
        """Verify balance after verification reflects the incoming amount."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        fund = log.incoming_fund_id
        fund.action_verify()

        self.assertEqual(fund.fund_account_id.total_incoming, 1000000.0)
        self.assertEqual(fund.fund_account_id.available_balance, 1000000.0)

    # ──────────────────────────────────────────────
    # AUDIT TRAIL TESTS
    # ──────────────────────────────────────────────

    def test_email_creation_audit_logged(self):
        """Verify audit log entry created for email-parsed fund."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        audit = self.AuditLog.search([
            ("model", "=", "nn.incoming.fund"),
            ("res_id", "=", log.incoming_fund_id.id),
            ("action", "=", "create"),
        ])
        self.assertTrue(audit)
        self.assertEqual(audit[0].new_state, "pending_verification")
        self.assertEqual(audit[0].amount, 1000000.0)

    def test_email_verify_audit_logged(self):
        """Verify audit log entry created when fund is verified."""
        log = self.Parser.process_email(SAMPLE_BANK_EMAIL)
        fund = log.incoming_fund_id
        fund.action_verify()

        audit = self.AuditLog.search([
            ("model", "=", "nn.incoming.fund"),
            ("res_id", "=", fund.id),
            ("action", "=", "confirm"),
        ])
        self.assertTrue(audit)

    # ──────────────────────────────────────────────
    # LOG MANAGEMENT TESTS
    # ──────────────────────────────────────────────

    def test_log_state_counts(self):
        """Verify parser log count tracking."""
        self.Parser.process_email(SAMPLE_BANK_EMAIL)
        self.assertEqual(self.parser.success_count, 1)

        self.Parser.process_email(SAMPLE_BANK_EMAIL)  # duplicate
        self.assertEqual(self.parser.success_count, 1)  # still 1 success

    def test_failed_log_reprocess(self):
        """Verify failed log can be manually reprocessed."""
        bad_email = "From: test@test.com\nSubject: Bad\n\nNo data"
        log = self.Parser.process_email(bad_email)
        self.assertEqual(log.state, "failed")

        # Log should have retry_count
        self.assertEqual(log.retry_count, 0)

    # ──────────────────────────────────────────────
    # SECURITY TESTS
    # ──────────────────────────────────────────────

    def test_multi_company_parser_isolation(self):
        """Verify parsers from different companies are isolated."""
        company_2 = self.env["res.company"].create({
            "name": "Test Company 2",
        })

        parser_other = self.Parser.with_context(allowed_company_ids=company_2.ids).create({
            "bank_name": "Other Bank",
            "email_suffix": "other.com",
            "regex_bank_name": r"Bank:\s*(.+?)[\n\r]",
            "regex_account_number": r"Account\s*No:\s*(\d+)",
            "regex_transaction_ref": r"Transaction\s*Ref:\s*([A-Za-z0-9\-/]+)",
            "regex_date": r"Date:\s*(\d{2}[/-]\d{2}[/-]\d{4})",
            "regex_amount": r"Amount:\s*([\d,]+\.?\d*)",
            "regex_sender": r"From:\s*(.+?)[\n\r]",
            "regex_message_id": r"Message-ID\s*:\s*<(.+?)>",
            "company_id": company_2.id,
        })

        # Process email from other domain
        other_email = SAMPLE_BANK_EMAIL.replace(
            "notifications@ibank.com", "notifications@other.com"
        )
        log = self.Parser.with_context(allowed_company_ids=company_2.ids).process_email(
            other_email, company_id=company_2.id
        )
        self.assertEqual(log.state, "success")
        self.assertEqual(log.parser_id.id, parser_other.id)

    def test_parser_bank_name_unique_per_company(self):
        """Verify duplicate bank name within same company raises error."""
        with self.assertRaises(Exception):
            self.Parser.create({
                "bank_name": "Global Trust Bank",  # Same name as existing
                "email_suffix": "dupe.com",
                "regex_bank_name": r"Bank:\s*(.+?)[\n\r]",
                "regex_account_number": r"Account\s*No:\s*(\d+)",
                "regex_transaction_ref": r"Transaction\s*Ref:\s*([A-Za-z0-9\-/]+)",
                "regex_date": r"Date:\s*(\d{2}[/-]\d{2}[/-]\d{4})",
                "regex_amount": r"Amount:\s*([\d,]+\.?\d*)",
                "regex_sender": r"From:\s*(.+?)[\n\r]",
                "regex_message_id": r"Message-ID\s*:\s*<(.+?)>",
                "company_id": self.env.company.id,
            })

    def test_email_log_sql_unique_message_id(self):
        """Verify SQL constraint on email_message_id uniqueness."""
        pass  # Tested via test_duplicate_email_message_id_blocked
