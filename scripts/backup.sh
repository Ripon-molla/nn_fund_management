#!/bin/bash
#================================================================
# NN Fund Management — Production Backup Script
# Creates timestamped PostgreSQL + filestore backups
# Supports local retention and optional S3 sync
#================================================================
set -euo pipefail

# Configuration with defaults
BACKUP_DIR="${BACKUP_DIR:-/backup}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-nn_fund_management}"
DB_USER="${DB_USER:-odoo}"
DB_PASSWORD="${DB_PASSWORD:-}"
FILESTORE_DIR="${FILESTORE_DIR:-/opt/odoo/filestore}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
S3_BUCKET="${AWS_S3_BUCKET:-}"
S3_ENDPOINT="${AWS_S3_ENDPOINT:-}"
LOG_FILE="${BACKUP_DIR}/backup.log"

# Color output
info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*" | tee -a "$LOG_FILE"; }
warn()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN]  $*" | tee -a "$LOG_FILE"; }
error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"; exit 1; }

# Validate required tools
check_dependencies() {
    command -v pg_dump >/dev/null 2>&1 || error "pg_dump not found"
    command -v gzip >/dev/null 2>&1 || error "gzip not found"
    command -v aws >/dev/null 2>&1 || warn "aws CLI not found — S3 sync disabled"
}

# Create backup directory
init_backup() {
    mkdir -p "$BACKUP_PATH"
    info "Backup directory created: ${BACKUP_PATH}"
}

# Backup PostgreSQL database (compressed)
backup_database() {
    info "Starting PostgreSQL backup: ${DB_NAME}"
    local db_file="${BACKUP_PATH}/${DB_NAME}_${TIMESTAMP}.sql"

    export PGPASSWORD="$DB_PASSWORD"
    pg_dump \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --format=custom \
        --compress=9 \
        --verbose \
        --no-owner \
        --no-acl \
        --file="${db_file}.dump" 2>&1 | tee -a "$LOG_FILE"

    # Also create plain SQL backup for emergency restores
    pg_dump \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --format=plain \
        --no-owner \
        --no-acl \
        --file="${db_file}" 2>&1 | tee -a "$LOG_FILE"

    gzip -9 "${db_file}"
    unset PGPASSWORD

    local size=$(stat -c%s "${db_file}.dump" 2>/dev/null || stat -f%z "${db_file}.dump" 2>/dev/null)
    info "Database backup completed: ${db_file}.dump (${size} bytes)"
}

# Backup Odoo filestore
backup_filestore() {
    info "Starting filestore backup"
    local filestore_archive="${BACKUP_PATH}/filestore_${TIMESTAMP}.tar.gz"

    if [ -d "$FILESTORE_DIR" ]; then
        tar -czf "$filestore_archive" \
            --exclude="*.tmp" \
            --exclude="*.log" \
            -C "$(dirname $FILESTORE_DIR)" \
            "$(basename $FILESTORE_DIR)" 2>&1 | tee -a "$LOG_FILE"
        local size=$(stat -c%s "$filestore_archive" 2>/dev/null || stat -f%z "$filestore_archive" 2>/dev/null)
        info "Filestore backup completed: ${filestore_archive} (${size} bytes)"
    else
        warn "Filestore directory not found: ${FILESTORE_DIR}"
    fi
}

# Generate backup manifest
generate_manifest() {
    local manifest="${BACKUP_PATH}/manifest.txt"
    {
        echo "Backup Timestamp: ${TIMESTAMP}"
        echo "Database: ${DB_NAME}"
        echo "Host: ${DB_HOST}:${DB_PORT}"
        echo "Filestore: ${FILESTORE_DIR}"
        echo ""
        echo "Contents:"
        ls -lh "${BACKUP_PATH}/"
    } > "$manifest"
    info "Manifest created: ${manifest}"
}

# Sync to S3 if configured
sync_to_s3() {
    if [ -n "$S3_BUCKET" ] && command -v aws >/dev/null 2>&1; then
        info "Syncing to S3: s3://${S3_BUCKET}/backups/"
        aws s3 sync "$BACKUP_DIR" "s3://${S3_BUCKET}/backups/" \
            --endpoint-url="${S3_ENDPOINT}" \
            --storage-class=STANDARD_IA \
            --only-show-errors 2>&1 | tee -a "$LOG_FILE"
        info "S3 sync completed"
    else
        info "S3 sync skipped (not configured)"
    fi
}

# Cleanup old backups
cleanup_old_backups() {
    info "Cleaning backups older than ${RETENTION_DAYS} days"
    find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -exec rm -rf {} \;
    find "$BACKUP_DIR" -name "*.log" -mtime "+${RETENTION_DAYS}" -delete
    info "Cleanup completed"
}

# Verify backup integrity
verify_backup() {
    info "Verifying backup integrity"
    local db_dump="${BACKUP_PATH}/${DB_NAME}_${TIMESTAMP}.sql.dump"
    if [ -f "$db_dump" ]; then
        pg_restore --list "$db_dump" > /dev/null 2>&1 && \
            info "Database backup integrity verified" || \
            warn "Database backup may be corrupted"
    fi
}

# Main
main() {
    info "=== NN Fund Management Backup ==="
    info "Starting at $(date)"
    check_dependencies
    init_backup
    backup_database
    backup_filestore
    generate_manifest
    verify_backup
    sync_to_s3
    cleanup_old_backups
    info "Backup completed successfully at $(date)"
}

main "$@"
