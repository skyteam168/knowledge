#!/usr/bin/env bash
# Validate observability alert rules / configs without requiring a full stack.
# Usage (from deploy/):
#   ./observability/verify-alerts.sh
# Optional: PROM_IMAGE=prom/prometheus:v3.2.1 AM_IMAGE=prom/alertmanager:v0.28.1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OBS="$ROOT/observability"
PROM_IMAGE="${PROM_IMAGE:-prom/prometheus:v3.2.1}"
AM_IMAGE="${AM_IMAGE:-prom/alertmanager:v0.28.1}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/docker-compose.prod.yml}"
WEBHOOK_URL="${ALERTMANAGER_WEBHOOK_URL:-http://127.0.0.1:9/}"

echo "== D2 verify-alerts =="
echo "root=$ROOT"
echo "prom_image=$PROM_IMAGE"
echo "am_image=$AM_IMAGE"

echo
echo "-- 1) compose file declares observability profile services"
for svc in prometheus alertmanager grafana otel-collector jaeger node-exporter; do
  grep -E "^  ${svc}:" "$COMPOSE_FILE" >/dev/null
done
grep -E 'profiles: \["observability"\]' "$COMPOSE_FILE" >/dev/null
ENV_FILE="$ROOT/.env.prod"
[[ -f "$ENV_FILE" ]] || ENV_FILE="$ROOT/.env.prod.example"
if [[ -f "$ENV_FILE" ]]; then
  if CFG_OUT="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile observability config 2>&1)"; then
    echo "$CFG_OUT" | grep -E '^  prometheus:' >/dev/null
    echo "OK compose config interpolated ($ENV_FILE)"
  else
    echo "WARN compose config skipped (env incomplete)"
    echo "OK compose YAML declares observability services"
  fi
else
  echo "OK compose YAML declares observability services"
fi

echo
echo "-- 2) promtool check rules"
docker run --rm \
  -v "$OBS/alerts.yml:/etc/prometheus/alerts.yml:ro" \
  --entrypoint promtool \
  "$PROM_IMAGE" check rules /etc/prometheus/alerts.yml
ALERT_COUNT="$(grep -cE '^\s*- alert:' "$OBS/alerts.yml" || true)"
[[ "$ALERT_COUNT" -ge 1 ]]
echo "OK rules loaded (alert count=$ALERT_COUNT)"

echo
echo "-- 3) promtool check config (needs dummy metrics-token for credentials_file)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp "$OBS/prometheus.yml" "$TMP/prometheus.yml"
cp "$OBS/alerts.yml" "$TMP/alerts.yml"
printf 'drill-token\n' >"$TMP/metrics-token"
# Rewrite rule/credentials paths for the container mount.
sed -i.bak \
  -e 's|/etc/prometheus/alerts.yml|/work/alerts.yml|' \
  -e 's|/etc/prometheus/metrics-token|/work/metrics-token|' \
  "$TMP/prometheus.yml"
docker run --rm \
  -v "$TMP:/work:ro" \
  --entrypoint promtool \
  "$PROM_IMAGE" check config /work/prometheus.yml
echo "OK prometheus config"

echo
echo "-- 4) amtool check-config (rendered webhook)"
RENDERED="$TMP/alertmanager.yml"
sed "s|__WEBHOOK_URL__|${WEBHOOK_URL}|g" "$OBS/alertmanager.yml.tmpl" >"$RENDERED"
docker run --rm \
  -v "$RENDERED:/tmp/alertmanager.yml:ro" \
  --entrypoint amtool \
  "$AM_IMAGE" check-config /tmp/alertmanager.yml
echo "OK alertmanager config (webhook=$WEBHOOK_URL)"

echo
echo "SUCCESS verify-alerts"
echo "ALERT_COUNT=$ALERT_COUNT"
