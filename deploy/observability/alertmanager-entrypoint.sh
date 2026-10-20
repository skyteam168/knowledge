#!/bin/sh
# Render alertmanager.yml from template (official image has busybox sed/sh).
set -eu
URL="${ALERTMANAGER_WEBHOOK_URL:-http://127.0.0.1:9}"
# Escape sed replacement metacharacters in URL
ESCAPED=$(printf '%s' "$URL" | sed -e 's/[&|\\]/\\&/g')
sed "s|__WEBHOOK_URL__|${ESCAPED}|g" /etc/alertmanager/alertmanager.yml.tmpl \
  > /tmp/alertmanager.yml
exec /bin/alertmanager \
  --config.file=/tmp/alertmanager.yml \
  --storage.path=/alertmanager \
  "$@"
