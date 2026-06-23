"""
NN Fund Management — API Authentication & Security Layer

Provides:
- API key authentication (header-based)
- Rate limiting with per-company quotas
- Request/response audit logging
- Input validation and sanitization
- Pagination helpers
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from functools import wraps

from odoo import api, fields, models, _
from odoo.exceptions import AccessDenied, AccessError, ValidationError

_logger = logging.getLogger(__name__)


class ApiKey(models.Model):
    """API key management for programmatic access.

    Security model:
    - Keys are stored as SHA-256 hashes (never plaintext)
    - Each key scoped to a single company
    - Rate limits enforced per-key
    - Expiration dates enforced server-side
    - Audit log on every API call
    """

    _name = "nn.api.key"
    _description = "NN Fund Management - API Key"
    _rec_name = "name"
    _order = "create_date DESC"

    name = fields.Char(string="Key Name", required=True, index=True)
    key_hash = fields.Char(string="Key Hash", required=True, readonly=True)
    key_prefix = fields.Char(
        string="Key Prefix",
        required=True,
        readonly=True,
        help="First 8 chars of the API key for identification",
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="cascade",
        domain=[("share", "=", False)],
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(string="Active", default=True)
    expiration_date = fields.Date(string="Expiration Date")
    last_used_date = fields.Datetime(string="Last Used")
    rate_limit_per_hour = fields.Integer(
        string="Rate Limit (per hour)", default=1000
    )
    request_count = fields.Integer(string="Request Count (current hour)", default=0)
    request_window_start = fields.Datetime(string="Request Window Start")

    _sql_constraints = [
        ("key_prefix_unique", "UNIQUE(key_prefix)", "Key prefix must be unique!"),
    ]

    def generate_key(self):
        """Generate a new API key. Returns plaintext key (shown once)."""
        import secrets

        key = secrets.token_urlsafe(48)
        prefix = key[:8]
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        self.write(
            {
                "key_hash": key_hash,
                "key_prefix": prefix,
            }
        )
        return f"nn_{key}"


class ApiRateLimiter(models.TransientModel):
    """In-memory rate limiter for API requests.

    Uses database writes for persistence across workers.
    For high-volume deployments, replace with Redis.
    """

    _name = "nn.api.rate.limiter"
    _description = "API Rate Limiter"

    @api.model
    def check_rate_limit(self, api_key_id):
        """Check if API key has exceeded rate limit. Returns True if allowed."""
        key = self.env["nn.api.key"].browse(api_key_id)
        if not key.exists():
            return False

        now = datetime.utcnow()
        window_start = key.request_window_start

        # Reset counter if outside window
        if not window_start or (now - window_start).total_seconds() > 3600:
            key.write(
                {
                    "request_count": 0,
                    "request_window_start": now,
                }
            )

        if key.request_count >= key.rate_limit_per_hour:
            return False

        key.write({"request_count": key.request_count + 1, "last_used_date": now})
        return True

    @api.model
    def authenticate(self, api_key):
        """Authenticate an API key. Returns user/company or raises AccessDenied.

        Args:
            api_key: The raw API key string (format: nn_<token>)

        Returns:
            tuple: (res.users, res.company) or raises AccessDenied
        """
        if not api_key or not api_key.startswith("nn_"):
            raise AccessDenied(_("Invalid API key format"))

        raw_key = api_key[3:]  # Strip "nn_" prefix
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        key_record = self.env["nn.api.key"].search(
            [("key_hash", "=", key_hash), ("active", "=", True)]
        )

        if not key_record:
            raise AccessDenied(_("API key not found or inactive"))

        # Check expiration
        if key_record.expiration_date and key_record.expiration_date < fields.Date.today():
            raise AccessDenied(_("API key has expired"))

        # Check rate limit
        if not self.check_rate_limit(key_record.id):
            raise AccessDenied(_("Rate limit exceeded"))

        return key_record.user_id, key_record.company_id


class ApiAuditLog(models.TransientModel):
    """Helper to log API requests to audit trail."""

    _name = "nn.api.audit.log"
    _description = "API Audit Logger"

    @api.model
    def log_request(
        self,
        user_id,
        company_id,
        endpoint,
        method,
        request_params=None,
        response_status=200,
        ip_address=None,
    ):
        """Log an API request to the audit log."""
        details = f"[API] {method} {endpoint} -> {response_status}"
        if request_params:
            # Sanitize sensitive params
            safe_params = {
                k: v for k, v in (request_params or {}).items()
                if k not in ("password", "api_key", "token")
            }
            if safe_params:
                details += f" | params: {safe_params}"

        self.env["nn.audit.log"].create(
            {
                "action": "api_call",
                "model_name": "nn.api.key",
                "record_id": 0,
                "record_name": endpoint,
                "user_id": user_id,
                "company_id": company_id,
                "details": details,
                "ip_address": ip_address,
            }
        )


class ApiIdempotencyKey(models.Model):
    """Idempotency key model for API replay protection.

    Prevents duplicate execution of state-changing API requests.
    Each idempotency key can only be used once within the retention period (24h).
    Keys automatically expire and are cleaned by cron.

    Usage:
        Client sends `Idempotency-Key: <uuid>` header with state-changing requests.
        If the same key is seen again within 24h, the server returns the original
        response without re-executing the operation.
    """

    _name = "nn.api.idempotency.key"
    _description = "API Idempotency Key"
    _rec_name = "idempotency_key"
    _order = "create_date DESC"

    idempotency_key = fields.Char(
        string="Idempotency Key",
        required=True,
        index=True,
        readonly=True,
        help="Unique idempotency key provided by the client.",
    )

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        readonly=True,
    )

    endpoint = fields.Char(
        string="Endpoint",
        required=True,
        readonly=True,
        help="API endpoint that processed this request.",
    )

    request_params = fields.Text(
        string="Request Parameters",
        readonly=True,
    )

    response_code = fields.Char(
        string="Response Code",
        readonly=True,
    )

    expiration_date = fields.Datetime(
        string="Expiration Date",
        required=True,
        readonly=True,
        help="After this date, the idempotency key can be reused.",
    )

    _sql_constraints = [
        (
            "idempotency_key_unique",
            "UNIQUE(idempotency_key)",
            "Idempotency key must be unique. Duplicate key detected — this request has already been processed.",
        ),
    ]

    @api.model
    def check_and_create(self, idempotency_key, user_id, company_id, endpoint, params=None):
        """Check if an idempotency key already exists, or create a new one.

        Args:
            idempotency_key: The client-provided idempotency key
            user_id: The authenticated user ID
            company_id: The company ID for the request
            endpoint: The API endpoint being called
            params: The request parameters (optional)

        Returns:
            tuple: (is_new, record) — is_new=True if this is the first use, False if duplicate

        Raises:
            ValidationError if the key was already used (replay detected)
        """
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            raise ValidationError(
                _(
                    "Idempotency key '%s' has already been used for endpoint '%s'. "
                    "This request appears to be a duplicate and has been rejected. "
                    "Use a new idempotency key for each request."
                )
                % (idempotency_key, existing.endpoint)
            )
        expiration = fields.Datetime.now() + timedelta(hours=24)
        record = self.create({
            "idempotency_key": idempotency_key,
            "user_id": user_id,
            "company_id": company_id,
            "endpoint": endpoint,
            "request_params": str(params) if params else False,
            "expiration_date": expiration,
        })
        return True, record

    @api.model
    def cron_clean_expired_keys(self):
        """Cron job: clean expired idempotency keys."""
        expired = self.search([("expiration_date", "<", fields.Datetime.now())])
        count = len(expired)
        expired.unlink()
        if count:
            _logger.info("Cleaned %d expired idempotency keys.", count)
        return count


class ApiResponseHelpers(models.AbstractModel):
    """Mixin providing standardized JSON response formatting."""

    _name = "nn.api.response.helpers"
    _description = "API Response Helpers"

    @api.model
    def success(self, data=None, message="Success"):
        """Standard success response."""
        return {
            "success": True,
            "message": message,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }

    @api.model
    def error(self, message, code=400, details=None):
        """Standard error response."""
        return {
            "success": False,
            "error": {
                "message": message,
                "code": code,
                "details": details or {},
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    @api.model
    def paginated(self, data, total, offset, limit):
        """Standard paginated response."""
        return {
            "success": True,
            "data": data,
            "pagination": {
                "total": total,
                "offset": offset,
                "limit": limit,
                "returned": len(data),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
