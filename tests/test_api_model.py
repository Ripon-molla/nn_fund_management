from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessDenied


@tagged("post_install", "-at_install", "fund_management", "api")
class TestApiKey(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, no_reset_password=True))
        cls.user = cls.env.ref("base.user_admin")
        cls.api_key = cls.env["nn.api.key"].create({
            "name": "Test API Key",
            "user_id": cls.user.id,
            "company_id": cls.env.company.id,
            "key_hash": "abc123hash",
            "key_prefix": "TESTKEY-",
            "rate_limit_per_hour": 100,
        })

    # ── generate_key ──
    def test_01_generate_key_returns_hashed(self):
        key_obj = self.env["nn.api.key"].create({
            "name": "New Key",
            "user_id": self.user.id,
            "company_id": self.env.company.id,
            "key_hash": "placeholder",
            "key_prefix": "PLACEH-",
        })
        raw_key = key_obj.generate_key()
        self.assertTrue(raw_key.startswith("nn_"))
        self.assertEqual(len(raw_key), 51)
        self.assertNotEqual(key_obj.key_hash, "placeholder")
        self.assertNotEqual(key_obj.key_hash, raw_key)

    # ── SQL constraint: key_prefix_unique ──
    def test_02_key_prefix_unique(self):
        with self.assertRaises(Exception):
            self.env["nn.api.key"].create({
                "name": "Dup Prefix",
                "user_id": self.user.id,
                "company_id": self.env.company.id,
                "key_hash": "anotherhash",
                "key_prefix": "TESTKEY-",
            })

    # ── rate limiting ──
    def test_03_rate_limiter_allows_request(self):
        limiter = self.env["nn.api.rate.limiter"]
        result = limiter.check_rate_limit(self.api_key.id)
        self.assertTrue(result)

    def test_04_rate_limiter_blocks_over_limit(self):
        limiter = self.env["nn.api.rate.limiter"]
        self.api_key.write({"rate_limit_per_hour": 2, "request_count": 0})
        self.assertTrue(limiter.check_rate_limit(self.api_key.id))
        self.assertTrue(limiter.check_rate_limit(self.api_key.id))
        result = limiter.check_rate_limit(self.api_key.id)
        self.assertFalse(result)

    def test_05_rate_limiter_invalid_key(self):
        limiter = self.env["nn.api.rate.limiter"]
        result = limiter.check_rate_limit(999999)
        self.assertFalse(result)

    # ── authenticate ──
    def test_06_authenticate_invalid_format(self):
        limiter = self.env["nn.api.rate.limiter"]
        with self.assertRaises(AccessDenied):
            limiter.authenticate("invalid-key")

    def test_07_authenticate_key_not_found(self):
        limiter = self.env["nn.api.rate.limiter"]
        with self.assertRaises(AccessDenied):
            limiter.authenticate("nn_nonexistentkeyhash")

    def test_08_authenticate_expired_key(self):
        import hashlib
        raw = "testexpiredkey12345"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        key = self.env["nn.api.key"].create({
            "name": "Expired Key",
            "user_id": self.user.id,
            "company_id": self.env.company.id,
            "key_hash": key_hash,
            "key_prefix": "EXPIRED-",
            "expiration_date": "2020-01-01",
        })
        limiter = self.env["nn.api.rate.limiter"]
        with self.assertRaises(AccessDenied):
            limiter.authenticate(f"nn_{raw}")

    def test_09_authenticate_inactive_key(self):
        import hashlib
        raw = "inactivekey12345"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        self.env["nn.api.key"].create({
            "name": "Inactive Key",
            "user_id": self.user.id,
            "company_id": self.env.company.id,
            "key_hash": key_hash,
            "key_prefix": "INACTV-",
            "active": False,
        })
        limiter = self.env["nn.api.rate.limiter"]
        with self.assertRaises(AccessDenied):
            limiter.authenticate(f"nn_{raw}")

    def test_10_authenticate_success(self):
        import hashlib
        raw = "validkey123456789"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        self.env["nn.api.key"].create({
            "name": "Valid Key",
            "user_id": self.user.id,
            "company_id": self.env.company.id,
            "key_hash": key_hash,
            "key_prefix": "VALIDK-",
            "rate_limit_per_hour": 1000,
        })
        limiter = self.env["nn.api.rate.limiter"]
        user, company = limiter.authenticate(f"nn_{raw}")
        self.assertEqual(user.id, self.user.id)
        self.assertEqual(company.id, self.env.company.id)

    # ── ApiAuditLog ──
    def test_11_api_audit_log_creates_record(self):
        audit = self.env["nn.api.audit.log"]
        audit.log_request(
            user_id=self.user.id,
            company_id=self.env.company.id,
            endpoint="/api/v1/test",
            method="GET",
            response_status=200,
        )
        log = self.env["nn.audit.log"].search([
            ("action", "=", "api_call"),
            ("record_name", "=", "/api/v1/test"),
        ], limit=1)
        self.assertTrue(log)
        self.assertIn("[API] GET /api/v1/test -> 200", log.details)

    def test_12_api_audit_log_sanitizes_password(self):
        audit = self.env["nn.api.audit.log"]
        audit.log_request(
            user_id=self.user.id,
            company_id=self.env.company.id,
            endpoint="/api/v1/test",
            method="POST",
            request_params={"password": "secret123", "amount": 500},
            response_status=200,
        )
        log = self.env["nn.audit.log"].search([
            ("action", "=", "api_call"),
        ], order="create_date DESC", limit=1)
        self.assertNotIn("secret123", log.details)
        self.assertIn("500", log.details)

    # ── ApiResponseHelpers ──
    def test_13_response_success(self):
        helper = self.env["nn.api.response.helpers"]
        result = helper.success(data={"key": "value"}, message="OK")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "OK")
        self.assertEqual(result["data"]["key"], "value")

    def test_14_response_error(self):
        helper = self.env["nn.api.response.helpers"]
        result = helper.error("Something broke", code=500, details={"trace": "err"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], 500)

    def test_15_response_paginated(self):
        helper = self.env["nn.api.response.helpers"]
        result = helper.paginated(["a", "b"], total=10, offset=0, limit=2)
        self.assertTrue(result["success"])
        self.assertEqual(result["pagination"]["total"], 10)
        self.assertEqual(result["pagination"]["returned"], 2)
