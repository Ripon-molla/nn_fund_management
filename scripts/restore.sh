#!/bin/bash
#================================================================
# NN Fund Management — Production Restore Script
# Usage: ./restore.sh <backup_timestamp> [db_name]
# Example: ./restore.sh 20250101_020000 nn_fund_management_restore
#================================================================
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "ERROR: Missing backup timestamp"
    echo "Usage: $0 <backup_timestamp> [db_name]"
    echo "Example: $0 20250101_020000 nn_fund_management_restore"
    exit 1
fi

TIMESTAMP="$1"
DB_NAME="${2:-nn_fund_management_restore}"
BACKUP_DIR="${BACKUP_DIR:-/backup}"
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-odoo}"
DB_PASSWORD="${DB_PASSWORD:-}"
FILESTORE_DIR="${FILESTORE_DIR:-/opt/odoo/filestore}"
LOG_FILE="${BACKUP_DIR}/restore_${TIMESTAMP}.log"

info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*" | tee -a "$LOG_FILE"; }
error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"; exit 1; }

check_prerequisites() {
    command -v pg_restore >/dev/null 2>&1 || error "pg_restore not found"
    command -v psql >/dev/null 2>&1 || error "psql not found"

    if [ ! -d "$BACKUP_PATH" ]; then
        error "Backup directory not found: ${BACKUP_PATH}"
    fi
}

restore_database() {
    local db_dump="${BACKUP_PATH}/nn_fund_management_${TIMESTAMP}.sql.dump"
    local sql_file="${BACKUP_PATH}/nn_fund_management_${TIMESTAMP}.sql.gz"

    info "Creating database: ${DB_NAME}"
    export PGPASSWORD="$DB_PASSWORD"

    # Drop if exists and recreate
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
        -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\" ENCODING 'UTF8';"

    # Restore from custom dump (preferred)
    if [ -f "$db_dump" ]; then
        info "Restoring from custom format dump: ${db_dump}"
        pg_restore \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            --dbname="$DB_NAME" \
            --jobs=4 \
            --verbose \
            --no-owner \
            --no-acl \
            "$db_dump" 2>&1 | tee -a "$LOG_FILE"
    # Fallback to plain SQL
    elif [ -f "$sql_file" ]; then
        info "Restoring from SQL dump: ${sql_file}"
        gunzip -c "$sql_file" | psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" 2>&1 | tee -a "$LOG_FILE"
    else
        error "No backup files found in ${BACKUP_PATH}"
    fi

    unset PGPASSWORD
    info "Database restore completed: ${DB_NAME}"
}

restore_filestore() {
    local filestore_archive="${BACKUP_PATH}/filestore_${TIMESTAMP}.tar.gz"
    if [ -f "$filestore_archive" ]; then
        info "Restoring filestore from: ${filestore_archive}"
        tar -xzf "$filestore_archive" -C "$(dirname $FILESTORE_DIR)"
        info "Filestore restore completed"
    else
        info "No filestore backup found — skipping"
    fi
}

verify_restore() {
    info "Verifying restore..."
    export PGPASSWORD="$DB_PASSWORD"
    local table_count=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d ' ')
    unset PGPASSWORD
    info "Database has ${table_count} tables"
    echo ""
    echo "============================================"
    echo " RESTORE COMPLETED SUCCESSFULLY"
    echo " Database: ${DB_NAME}"
    echo " Tables:   ${table_count}"
    echo "============================================"
}

# Main
main() {
    echo "============================================"
    echo " NN FUND MANAGEMENT — RESTORE"
    echo " Timestamp: ${TIMESTAMP}"
    echo " Database:  ${DB_NAME}"
    echo "============================================"
    echo ""

    check_prerequisites
    restore_database
    restore_filestore
    verify_restore
}

main "$@"
