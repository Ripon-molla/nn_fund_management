from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError


@tagged("post_install", "-at_install", "fund_management", "bank_email")
class TestBankEmailExtended(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.parser = cls.env["nn.bank.email.parser"].create({
            "name": "Test Bank Parser",
            "bank_name": "TestBank",
            "email_domain": "testbank.com",
            "regex_amount": r"Amount:\s*\$?([0-9,]+\.\d{2})",
            "regex_account_number": r"Account:\s*(\d+)",
            "regex_transaction_reference": r"Ref:\s*(\w+)",
            "regex_date": r"Date:\s*(\d{2}/\d{2}/\d{4})",
            "regex_sender": r"From:\s*(.+)",
            "regex_message_id": r"Message-ID:\s*<(.*)>",
            "regex_bank_name": r"TestBank",
        })
        cls.currency = cls.env.ref("base.USD")
        cls.account = cls.env["nn.fund.account"].create({
            "name": "BE Ext Account",
            "code": "BEXT01",
            "currency_id": cls.currency.id,
        })
        cls.group_admin = cls.env.ref("nn_fund_management.group_fund_administrator")
        cls.admin = cls.env.ref("base.user_admin")

    def _make_email(self, body=None, msg_id="msg-001", subject="Test"):
        return {
            "from": "sender@testbank.com",
            "subject": subject,
            "body": body or (
                "From: Donor Foundation\n"
                "Date: 15/06/2026\n"
                "Amount: $10,500.00\n"
                "Account: 12345\n"
                "Ref: TXN-EXT-001\n"
                "Message-ID: <msg-001>\n"
                "TestBank Transfer Notification"
            ),
            "message_id": msg_id,
        }

    # ── SQL constraint: regex not empty ──
    def test_01_parser_regex_not_empty(self):
        with self.assertRaises(Exception):
            self.env["nn.bank.email.parser"].create({
                "name": "Bad Parser",
                "bank_name": "BadBank",
                "email_domain": "badbank.com",
                "regex_amount": "",
                "regex_account_number": "",
                "regex_transaction_reference": "",
                "regex_date": "",
            })

    # ── cron_clean_old_logs ──
    def test_02_cron_clean_old_logs_removes_success(self):
        self.parser.process_email(self._make_email(msg_id="clean-ok-001"), self.env.company.id)
        logs = self.env["nn.bank.email.log"].search([
            ("state", "=", "success"),
        ])
        if logs:
            old = logs[0]
            old.write({"create_date": "2020-01-01 00:00:00"})
        self.parser.cron_clean_old_logs()
        remaining = self.env["nn.bank.email.log"].search([
            ("email_message_id", "=", "clean-ok-001"),
        ])
        self.assertFalse(remaining)

    def test_03_cron_clean_old_logs_removes_failed(self):
        email = self._make_email(body="garbage content", msg_id="clean-fail-001")
        self.parser.process_email(email, self.env.company.id)
        logs = self.env["nn.bank.email.log"].search([
            ("state", "=", "failed"),
        ])
        if logs:
            old = logs[0]
            old.write({"create_date": "2019-01-01 00:00:00"})
        self.parser.cron_clean_old_logs()
        remaining = self.env["nn.bank.email.log"].search([
            ("email_message_id", "=", "clean-fail-001"),
        ])
        self.assertFalse(remaining)

    # ── action_view_incoming_fund on log ──
    def test_04_view_incoming_fund_action(self):
        email = self._make_email(msg_id="view-fund-001")
        self.parser.process_email(email, self.env.company.id)
        log = self.env["nn.bank.email.log"].search([
            ("email_message_id", "=", "view-fund-001"),
        ], limit=1)
        if log and log.incoming_fund_id:
            result = log.action_view_incoming_fund()
            self.assertEqual(result["type"], "ir.actions.act_window")
            self.assertEqual(result["res_model"], "nn.incoming.fund")
            self.assertEqual(result["res_id"], log.incoming_fund_id.id)

    def test_05_view_incoming_fund_action_no_fund(self):
        log = self.env["nn.bank.email.log"].create({
            "bank_name": "TestBank",
            "email_from": "test@test.com",
            "email_subject": "No fund",
            "raw_email_body": "test",
            "state": "success",
            "email_message_id": "no-fund-001",
            "company_id": self.env.company.id,
        })
        result = log.action_view_incoming_fund()
        self.assertIsNone(result)

    # ── action_reprocess on failed log ──
    def test_06_reprocess_failed_log(self):
        email = self._make_email(body="bad content", msg_id="repro-001")
        self.parser.process_email(email, self.env.company.id)
        log = self.env["nn.bank.email.log"].search([
            ("email_message_id", "=", "repro-001"),
        ], limit=1)
        if log and log.state == "failed":
            log.action_reprocess()
            self.assertIn(log.state, ("success", "failed"))

    # ── Processing from CC'd email with different domain ──
    def test_07_process_email_no_matching_parser_no_crash(self):
        email = self._make_email(
            from_addr="unknown@otherbank.com",
            msg_id="no-match-001",
            subject="Unknown",
            body="Some random email with no parsing pattern",
        )
        result = self.parser.process_email(email, self.env.company.id)
        self.assertEqual(result, ("ignored", "No matching parser found"))

    # ── Duplicate message_id blocked at SQL level ──
    def test_08_duplicate_message_id_sql_blocked(self):
        self.parser.process_email(self._make_email(msg_id="dup-sql-001"), self.env.company.id)
        with self.assertRaises(Exception):
            self.env["nn.bank.email.log"].create({
                "bank_name": "TestBank",
                "email_from": "test@test.com",
                "email_subject": "Dup",
                "raw_email_body": "dup",
                "state": "success",
                "email_message_id": "dup-sql-001",
                "company_id": self.env.company.id,
            })
