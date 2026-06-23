#!/bin/bash
set -e

#================================================================
# NN Fund Management - Odoo 18 Production Entrypoint
# Handles: DB wait, filestore init, migrations, server start
#================================================================

# Color output helpers
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*"; exit 1; }

# Wait for PostgreSQL
wait_for_db() {
    local host="${DB_HOST:-db}"
    local port="${DB_PORT:-5432}"
    local retries="${DB_WAIT_RETRIES:-60}"
    local delay="${DB_WAIT_DELAY:-2}"

    info "Waiting for PostgreSQL at ${host}:${port}..."
    for i in $(seq 1 "$retries"); do
        if pg_isready -h "$host" -p "$port" -q 2>/dev/null; then
            info "PostgreSQL is ready after ${i}s"
            return 0
        fi
        sleep "$delay"
    done
    error "PostgreSQL not reachable after ${retries}s"
}

# Initialize filestore directories
init_filestore() {
    mkdir -p /opt/odoo/data/filestore /opt/odoo/data/sessions
    chmod 777 /opt/odoo/data/sessions 2>/dev/null || true
}

# Create database if it doesn't exist (handles pre-existing pg volume)
create_db_if_missing() {
    local db="${DB_NAME:-nn_fund_management}"
    if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$db" -c "" 2>/dev/null; then
        info "Database '$db' already exists"
    else
        info "Database '$db' does not exist — creating..."
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "CREATE DATABASE \"$db\" OWNER \"$DB_USER\" ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0" 2>&1
        info "Database '$db' created"
    fi
}

# Run pending module upgrades
run_migrations() {
    local db="${DB_NAME:-nn_fund_management}"
    if [ "${RUN_MIGRATIONS:-true}" = "true" ] && [ -n "$db" ]; then
        info "Running module upgrades (db=$db)..."
        gosu odoo /usr/bin/odoo --config=/etc/odoo/odoo.conf \
             --database="$db" \
             --update=nn_fund_management \
             --stop-after-init \
             --no-http 2>&1 | tee -a /var/log/odoo/migration.log
        info "Module upgrades completed"
    fi
}

# Validate required secrets
validate_secrets() {
    if [ -z "$ADMIN_PASSWORD" ] && [ -f /run/secrets/admin_password ]; then
        export ADMIN_PASSWORD=$(cat /run/secrets/admin_password)
    fi
    if [ -z "$DB_PASSWORD" ] && [ -f /run/secrets/db_password ]; then
        export DB_PASSWORD=$(cat /run/secrets/db_password)
    fi
}

# Substitute env vars in config file (${VAR:-default} → actual values)
envsubst_config() {
    python3 <<'PYEOF'
import os, re
path = '/etc/odoo/odoo.conf'
with open(path) as f:
    c = f.read()
c = re.sub(r'\$\{(\w+):([^}]*)\}', lambda m: os.environ.get(m.group(1), m.group(2)), c)
with open(path, 'w') as f:
    f.write(c)
PYEOF
}

# Main execution
main() {
    validate_secrets
    envsubst_config
    wait_for_db
    create_db_if_missing
    init_filestore
    run_migrations

    info "Starting Odoo 18 server..."
    exec gosu odoo "$@"
}

main "$@"
