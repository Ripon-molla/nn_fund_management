# NN Fund Management

Enterprise-grade fund management system for Odoo 18 with full audit trail, double-spending prevention, configurable approval workflows, and real-time dashboard.

## Features

- **Fund Account Management** — Ledger-based architecture with real-time balance computation
- **Incoming Fund Tracking** — Bank email integration with automated parsing
- **Fund Allocations** — Multi-step approval workflow (GM / Finance / MD / Board)
- **Project & Expense Head Management** — Track budgets per project and expense category
- **Requisition & Bill Management** — Full procurement lifecycle with approval routing
- **Fund Transfers** — Inter-account transfers with automatic ledger posting
- **Configurable Approval Engine** — Dynamic approval matrix based on amount thresholds
- **Dashboard** — Real-time KPIs, charts, and transaction lists
- **Ledger Reconciliation** — Automated nightly reconciliation with health monitoring
- **REST API** — OAuth2-authenticated API with idempotency support
- **Multi-Company** — Complete company isolation with record rules
- **Audit Trail** — Full activity logging for all financial operations
- **Security Hardening** — Row-level locking, CSRF protection, duplicate prevention

## Installation

1. Copy the `nn_fund_management` directory to your Odoo `addons` path.
2. Update the app list: `odoo-bin -u all`
3. Install the module from Apps menu.

### Dependencies

- `base`
- `mail`
- `account`
- `web`

## Configuration

1. **Security Groups** — Assign users to appropriate groups:
   - Fund User (read-only access to financial data)
   - Finance User (operational access)
   - Fund Administrator (full access, emergency procedures)
   - GM Approver / MD Approver (approval workflow participants)

2. **Approval Matrix** — Configure amount-based approval rules under *Settings > Approval Matrices*.

3. **Bank Email** — Configure IMAP inbox under *Settings > Bank Email Parsers* for automated incoming fund detection.

## Demo Data

Install with demo data to get:
- Sample fund accounts (Main Operating, Project Reserve)
- Demo projects with expense heads
- Pre-configured approval matrices (3 tiers per request type)
- Demo users for each security group
- Initial 1,000,000 USD seed balance

### Demo Users

| Login  | Name         | Group              |
|--------|--------------|--------------------|
| alice  | Alice Finance | Finance User      |
| bob    | Bob GM       | GM Approver       |
| carol  | Carol MD     | MD Approver       |
| dave   | Dave Admin   | Fund Administrator |

All passwords match the login name.

## Development

### Code Quality

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### Testing

```bash
odoo-bin --test-tags nn_fund_management --addons-path addons -d test_db
```

### Docker

```bash
docker compose up -d
```

The production stack includes Odoo, PostgreSQL, Nginx, and automated backup services.

## Architecture

The module uses a **ledger-based accounting** model:

- Every financial transaction creates immutable ledger entries (`nn.fund.ledger`)
- Account balances are computed in real-time from ledger aggregates
- Double-spending prevention via `SELECT FOR UPDATE NOWAIT` row-level locks
- Transaction idempotency via UUID-based deduplication
- Automated nightly reconciliation cross-checks stored vs. derived balances

## Security

- All financial models inherit `nn.security.mixin` for centralized permission checks
- Multi-company isolation enforced at both ORM level (record rules) and application level
- State transition guards prevent invalid workflow moves
- Emergency reversal procedures with audit trail
- CSRF protection on all write operations
- Rate limiting on API endpoints

## License

MIT — see [LICENSE](LICENSE) for details.
