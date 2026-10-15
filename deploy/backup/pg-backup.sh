#!/bin/sh
# pg_dump of every database in BACKUP_DATABASES into /backups/pg/<UTC stamp>/, verified with
# pg_restore --list, older sets pruned after BACKUP_RETENTION_DAYS.
# Usage: pg-backup.sh [once]   (default: loop every BACKUP_INTERVAL_SECONDS)
set -eu

: "${BACKUP_DATABASES:=ekb keycloak}"
: "${BACKUP_RETENTION_DAYS:=14}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"
ROOT=/backups/pg

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
}

if [ "${1:-}" = "once" ]; then
    run_once
    exit 0
fi
while true; do
    run_once || echo "backup_failed" >&2
    sleep "$BACKUP_INTERVAL_SECONDS"
done
