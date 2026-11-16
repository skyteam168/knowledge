# 告警通道冒烟

本地 / 生产验收告警栈：规则语法、compose profile、可选 webhook 投递。

## 1. 无全栈：规则与配置门禁（必做）

在 `deploy/`：

```bash
# Linux / Git Bash
./observability/verify-alerts.sh

# Windows PowerShell
powershell -File .\observability\verify-alerts.ps1
```

脚本会：

1. `docker compose -f docker-compose.prod.yml --profile observability config` 断言含 `prometheus` / `alertmanager` / `grafana`
2. `promtool check rules` 校验 `observability/alerts.yml`
3. `promtool check config` 校验 `prometheus.yml`（临时 metrics-token）
4. 渲染 `alertmanager.yml.tmpl` 后 `amtool check-config`

可选环境变量：`PROM_IMAGE`、`AM_IMAGE`、`ALERTMANAGER_WEBHOOK_URL`、`COMPOSE_FILE`。

## 2. 全栈（可选）

```bash
cd deploy
grep ^METRICS_TOKEN= .env.prod | cut -d= -f2- > observability/metrics-token
# 或 PowerShell: (Get-Content .env.prod | ? { $_ -match '^METRICS_TOKEN=' }) -replace '^METRICS_TOKEN=','' | Set-Content observability/metrics-token
export ALERTMANAGER_WEBHOOK_URL=https://webhook.site/<your-uuid>
docker compose -f docker-compose.prod.yml --profile observability up -d
```

检查：

- Prometheus `http://127.0.0.1:9090/api/v1/rules` → `status=success`，规则组 `ekb`
- Alertmanager `http://127.0.0.1:9093/#/status` → 配置已加载
- 测试 firing（可选）：

```bash
curl -sS -XPOST http://127.0.0.1:9093/api/v2/alerts \
  -H 'Content-Type: application/json' \
  -d '[{"labels":{"alertname":"EkbDrillTest","severity":"warning","service":"ekb"},"annotations":{"summary":"drill"},"startsAt":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}]'
```

到 `ALERTMANAGER_WEBHOOK_URL` 对应页面确认收到 payload；未配置时默认丢弃到 `127.0.0.1:9`。

## 3. 规则清单

见 `deploy/observability/alerts.yml`：`EkbHighErrorRate`、`EkbSlowRequests`、`EkbSlowFirstToken`、`EkbLlmErrors`、`EkbQueueBacklog`、`EkbOutboxStuck`、`EkbOutboxDead`、`EkbTargetDown`、`BackupJobFailed`、`BackupJobStale`。
