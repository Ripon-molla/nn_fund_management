# NN Fund Management — REST API
# Last updated: June 2026
## Base URL

```
https://your-odoo-instance.com
```

## Authentication

API requests require an API key passed via the `X-API-Key` header.

### API Key Management

API keys are managed in Odoo via Settings > Fund Management > API Keys. Keys are:
- SHA-256 hashed at rest (plaintext only shown once at creation)
- Company-scoped
- Rate-limited (configurable)
- Expiring

## Endpoints

### Health Check

```
GET /health
```

No auth required. Returns JSON with database status.

### Dashboard

```
GET /api/v1/dashboard
```

Returns fund management dashboard metrics.

### Accounts

```
GET /api/v1/accounts
```

Returns all fund accounts.

```
GET /api/v1/accounts/<id>
```

Returns single fund account with balances.

### Incoming Funds

```
GET /api/v1/incoming-funds
```

Returns incoming fund records.

```
POST /api/v1/incoming-funds/verify/<id>
```

Verify an incoming fund (moves from pending_verification to verified).

### Allocations

```
GET /api/v1/allocations
```

Returns allocation records.

```
POST /api/v1/allocations/<id>/approve
```

Approve an allocation at current approval step.

```
POST /api/v1/allocations/<id>/reject
```

Reject an allocation.

### Transfers

```
GET /api/v1/transfers
```

Returns transfer records.

```
POST /api/v1/transfers/<id>/approve
```

Approve a transfer at current approval step.

### Requisitions

```
GET /api/v1/requisitions
```

Returns requisition records.

### Bills

```
GET /api/v1/bills
```

Returns bill records.

### Projects

```
GET /api/v1/projects
```

Returns project records.

### Expense Heads

```
GET /api/v1/expense-heads
```

Returns expense head records.

### Approval Actions

```
POST /api/v1/approve
```

Body: `{"model": "nn.fund.allocation", "res_id": 123}`

Approve a record by model and ID at the current approval step.

```
POST /api/v1/reject
```

Body: `{"model": "nn.fund.allocation", "res_id": 123}`

Reject a record by model and ID.

### Ledger

```
GET /api/v1/ledger
```

Returns ledger entries with optional filters:
- `?account_id=<id>`
- `?transaction_type=<type>`
- `?from_date=YYYY-MM-DD`
- `?to_date=YYYY-MM-DD`

### Audit Log

```
GET /api/v1/audit-log
```

Returns audit log entries.

## Rate Limiting

| Tier | Limit |
|---|---|
| API | 30 requests/second, burst 50 |
| Login | 5 requests/minute |
| Web | 100 requests/second, burst 200 |

## Error Responses

```json
{
    "error": "error_code",
    "message": "Human-readable error description"
}
```

Common error codes:
- `invalid_api_key` — Missing or invalid API key
- `expired_api_key` — API key has expired
- `rate_limit_exceeded` — Too many requests
- `access_denied` — Insufficient permissions
- `validation_error` — Invalid request data
- `not_found` — Resource not found
