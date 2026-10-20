#!/bin/sh
# Incremental copy of the document bucket into /backups/minio/<bucket>/ (objects deleted in
# MinIO are kept in the copy). staging/ holds unconfirmed uploads and is skipped.
# Writes Prometheus textfile metrics under /backups/metrics for node-exporter.
# Usage: minio-backup.sh [once]   (default: loop every BACKUP_INTERVAL_SECONDS)
set -eu

: "${MINIO_BUCKET:=ekb-documents}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
DEST="/backups/minio/$MINIO_BUCKET"
METRICS_DIR=/backups/metrics
JOB=minio

write_metrics() {
    status="$1"
    mkdir -p "$METRICS_DIR"
    out="$METRICS_DIR/ekb_backup_${JOB}.prom"
    tmp="$out.$$"
    prev_ts=0
    if [ -f "$out" ]; then
        prev_ts=$(awk '/^ekb_backup_job_success_timestamp/{print $2; exit}' "$out" || true)
        : "${prev_ts:=0}"
    fi
    ts=$(date +%s)
    success_ts="$prev_ts"
    if [ "$status" = "1" ]; then
        success_ts="$ts"
    fi
    {
        echo "# HELP ekb_backup_job_last_status 1 if last run succeeded, else 0"
        echo "# TYPE ekb_backup_job_last_status gauge"
        echo "ekb_backup_job_last_status{job=\"${JOB}\"} ${status}"
        echo "# HELP ekb_backup_job_success_timestamp Unix timestamp of last successful backup"
        echo "# TYPE ekb_backup_job_success_timestamp gauge"
        echo "ekb_backup_job_success_timestamp{job=\"${JOB}\"} ${success_ts}"
    } > "$tmp"
    mv "$tmp" "$out"
}

mc alias set src "${MINIO_ENDPOINT:-http://minio:9000}" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

run_once() {
    mkdir -p "$DEST"
    mc mirror --overwrite --preserve --exclude "staging/*" "src/$MINIO_BUCKET" "$DEST" >/dev/null
    echo "backup_ok $DEST $(du -sk "$DEST" | cut -f1)KiB"
    write_metrics 1
}

if [ "${1:-}" = "once" ]; then
    if run_once; then
        exit 0
    fi
    write_metrics 0
    exit 1
fi
while true; do
    if ! run_once; then
        echo "backup_failed" >&2
        write_metrics 0 || true
    fi
    sleep "$BACKUP_INTERVAL_SECONDS"
done
