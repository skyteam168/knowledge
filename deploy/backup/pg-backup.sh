#!/bin/sh
# pg_dump of every database in BACKUP_DATABASES into /backups/pg/<UTC stamp>/, verified with
# pg_restore --list, older sets pruned after BACKUP_RETENTION_DAYS.
# Writes Prometheus textfile metrics under /backups/metrics for node-exporter.
# Usage: pg-backup.sh [once]   (default: loop every BACKUP_INTERVAL_SECONDS)
set -eu

: "${BACKUP_DATABASES:=ekb keycloak}"
: "${BACKUP_RETENTION_DAYS:=14}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
ROOT=/backups/pg
METRICS_DIR=/backups/metrics
JOB=postgres

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

run_once() {
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    work="$ROOT/.$stamp.partial"
    mkdir -p "$work"
    for db in $BACKUP_DATABASES; do
        pg_dump --format=custom --dbname="$db" --file="$work/$db.dump"
        pg_restore --list "$work/$db.dump" >/dev/null
    done
    mv "$work" "$ROOT/$stamp"
    find "$ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$BACKUP_RETENTION_DAYS" -exec rm -rf {} +
    echo "backup_ok $ROOT/$stamp $(du -sk "$ROOT/$stamp" | cut -f1)KiB"
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
