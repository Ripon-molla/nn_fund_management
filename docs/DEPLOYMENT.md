# NN Fund Management — Deployment

## Production Stack

- PostgreSQL 16 (with SSL)
- Odoo 18 Community (2+ replicas for HA)
- Nginx (TLS termination, rate limiting, reverse proxy)
- Certbot (auto SSL renewal)
- Backup service (30-day retention, optional S3)

## Prerequisites

- Docker Engine 24+
- Docker Compose v2.20+
- Domain with DNS pointing to server
- Ports 80/443 open

## Quick Start

```bash
# Clone the repository
git clone <repo-url>
cd nn_fund_management

# Copy environment template
cp .env.example .env
# Edit .env with your values

# Deploy
docker compose -f docker/docker-compose.prod.yml up -d

# Check health
curl https://your-domain.com/health
```

## Environment Variables

See `.env.example` for all 30+ configurable variables. Key variables:

| Variable | Description |
|---|---|
| `DB_PASSWORD` | PostgreSQL password (use Docker secrets in prod) |
| `ADMIN_PASSWORD` | Odoo admin password |
| `ODOO_DB_HOST` | Database hostname |
| `ODOO_DB_PORT` | Database port (5432) |
| `ODOO_DB_USER` | Database user |
| `ODOO_DB_NAME` | Database name |
| `LONGPOLLING_PORT` | Odoo longpolling port (8072) |
| `SMTP_SERVER` | SMTP server for email parsing |
| `SMTP_PORT` | SMTP port |
| `SMTP_USER` | SMTP user |
| `SMTP_PASSWORD` | SMTP password (use Docker secrets) |
| `BACKUP_S3_BUCKET` | Optional S3 bucket for backups |
| `BACKUP_S3_ACCESS_KEY` | S3 access key |
| `BACKUP_S3_SECRET_KEY` | S3 secret key (use Docker secrets) |

## Docker Secrets

For production, never store credentials in `.env`. Use Docker secrets:

```bash
echo "your_db_password" | docker secret create db_password -
echo "your_admin_password" | docker secret create admin_password -
```

The entrypoint automatically reads secrets if env vars are empty.

## Scaling

Increase Odoo replicas in `docker-compose.prod.yml`:

```yaml
odoo:
    deploy:
        replicas: 4
```

Nginx `least_conn` load balancing distributes requests evenly.

## Backup & Restore

### Automated Backup

Docker service runs daily at 2 AM:
- Custom format dump (`pg_dump -Fc`)
- Plain SQL dump
- Filestore archive
- Local retention: 30 days
- Optional S3 sync

### Manual Restore

```bash
# List backups
docker exec backup ls /backups/daily/

# Restore from custom dump
docker exec backup bash /scripts/restore.sh \
    -f /backups/daily/odoo_20240101_020000.dump \
    -d odoo_prod
```

## Health Checks

```bash
# Nginx health
curl https://your-domain.com/health

# Odoo health (internal)
curl http://odoo:8069/health

# Full health script
docker exec odoo python /scripts/health_check.py
```

## CI/CD Pipeline

The `.github/workflows/ci.yml` pipeline:
1. Lint (black, flake8, isort, pylint-odoo)
2. Unit tests (PostgreSQL 16 service container)
3. Security scan (bandit, gitleaks, safety)
4. Docker build (multi-arch, Buildx cache)
5. Deploy (SSH + health check + Slack notification)
