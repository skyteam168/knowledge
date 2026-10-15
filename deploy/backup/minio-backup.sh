#!/bin/sh
# Incremental copy of the document bucket into /backups/minio/<bucket>/ (objects deleted in
# MinIO are kept in the copy). staging/ holds unconfirmed uploads and is skipped.
# Usage: minio-backup.sh [once]   (default: loop every BACKUP_INTERVAL_SECONDS)
set -eu

: "${MINIO_BUCKET:=ekb-documents}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
DEST="/backups/minio/$MINIO_BUCKET"

mc alias set src "${MINIO_ENDPOINT:-http://minio:9000}" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

run_once() {
    mkdir -p "$DEST"
    mc mirror --overwrite --preserve --exclude "staging/*" "src/$MINIO_BUCKET" "$DEST" >/dev/null
    echo "backup_ok $DEST $(du -sk "$DEST" | cut -f1)KiB"
}

if [ "${1:-}" = "once" ]; then
    run_once
    exit 0
fi
while true; do
    run_once || echo "backup_failed" >&2
    sleep "$BACKUP_INTERVAL_SECONDS"
done
