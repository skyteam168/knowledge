#!/bin/sh
set -e

# prometheus_client multiprocess mode: stale per-process files from a previous run would be summed in.
if [ -n "$PROMETHEUS_MULTIPROC_DIR" ]; then
    rm -rf "$PROMETHEUS_MULTIPROC_DIR"
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
fi

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
