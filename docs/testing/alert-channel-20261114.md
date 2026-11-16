# 告警通道验证纪要（本机）

> 日期：2026-11-14  
> 环境：Windows + Docker Desktop；仓库 `deploy/`  
> 对照：[`docs/ops/alerting-smoke.md`](../ops/alerting-smoke.md)、`deploy/observability/*`  
> 原则：**不强制起全栈 observability**；以 `promtool` / `amtool` + compose profile 门禁为 D2 验收。

---

## 1. 范围

| 项 | 本次 | 说明 |
| --- | --- | --- |
| observability profile 声明 | 已做 | `docker-compose.prod.yml` 含 prometheus / alertmanager / grafana 等 |
| 告警规则语法 | 已做 | `promtool check rules` → **10 rules** |
| Prometheus 配置 | 已做 | `promtool check config` SUCCESS |
| Alertmanager 配置（webhook 渲染） | 已做 | `amtool check-config` SUCCESS（默认 `http://127.0.0.1:9/`） |
| 全栈 up + 真实 webhook firing | **未做** | 可选；步骤见 `alerting-smoke.md` §2 |

---

## 2. 命令与结果

```text
cd deploy
powershell -NoProfile -ExecutionPolicy Bypass -File .\observability\verify-alerts.ps1
```

输出摘要：

```text
== D2 verify-alerts ==
-- 1) compose file declares observability profile services
OK compose config interpolated (...\.env.prod)
-- 2) promtool check rules
  SUCCESS: 10 rules found
OK rules loaded (alert count=10)
-- 3) promtool check config
 SUCCESS: /work/prometheus.yml is valid prometheus config file syntax
  SUCCESS: 10 rules found
OK prometheus config
-- 4) amtool check-config (rendered webhook)
Checking '/tmp/alertmanager.yml'  SUCCESS
OK alertmanager config (webhook=http://127.0.0.1:9/)
SUCCESS verify-alerts
ALERT_COUNT=10
```

镜像：`prom/prometheus:v3.2.1`、`prom/alertmanager:v0.28.1`（与 compose 对齐）。

---

## 3. 规则清单（已加载）

`EkbHighErrorRate`、`EkbSlowRequests`、`EkbSlowFirstToken`、`EkbLlmErrors`、`EkbQueueBacklog`、`EkbOutboxStuck`、`EkbOutboxDead`、`EkbTargetDown`、`BackupJobFailed`、`BackupJobStale`。

---

## 4. 结论

| 验收项 | 结果 |
| --- | --- |
| observability profile | 通过 |
| 本地规则加载 | 通过（10/10） |
| webhook 配置可渲染可校验 | 通过 |
| 脚本可复跑 | [`deploy/observability/verify-alerts.ps1`](../../deploy/observability/verify-alerts.ps1) / `.sh` |

生产投递：设置 `ALERTMANAGER_WEBHOOK_URL` 后按 `docs/ops/alerting-smoke.md` §2 起 profile 并可选 `POST /api/v2/alerts` 测 firing。
