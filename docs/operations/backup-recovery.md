# 备份、恢复与 RPO/RTO

> 本文是生产审计交付物。操作细节与 `docs/ops/backup-restore.md` 对齐并补充**已实现 vs 目标**差距。  
> **未完成的恢复演练不得标记为「灾备已通过」。**

---

## 1. 备份范围

| 组件 | 必须 | 当前自动化 | 说明 |
| --- | --- | --- | --- |
| PostgreSQL `ekb` + `keycloak` | 是 | compose `backup-postgres` 日级 `pg_dump -Fc` | 真相源 |
| MinIO 文档桶 | 是 | `backup-minio` mirror | 原文件 |
| Qdrant / OpenSearch | 否 | 可选快照 | 可从 PG+MinIO rebuild |
| Redis | 否 | — | outbox/缓存可重建 |
| `.env.prod.server`、证书、metrics token、realm | 是 | **人工** | 与数据备份分开放 |

详见 `docs/ops/backup-restore.md` §1–2。

---

## 2. RPO / RTO 目标（可配置意图）

| 指标 | 目标（建议） | **当前实现有效值** | 差距 |
| --- | --- | --- | --- |
| RPO（PG+MinIO） | ≤ 15 分钟（PITR + 异地） | ≈ **24 小时**（`BACKUP_INTERVAL_SECONDS=86400`） | 未落地 WAL/PITR、异地强制 |
| RTO（应用可登录） | ≤ 4 小时 | **unverifiable**（无演练计时） | 依赖机器与索引进度 |
| RTO（检索可用） | ≤ 8 小时（含 rebuild） | 取决于文档量；有 `index rebuild` | 需演练记录 |

环境变量可调备份间隔；**缩短间隔 ≠ PITR**，大库仍建议 basebackup + WAL。

---

## 3. 恢复步骤（摘要）

1. 准备新/干净环境：PG 建库、`pg_hba`、证书、`.env`。  
2. 停止写路径：`$DC stop backend worker outbox-dispatcher scheduler frontend`。  
3. 恢复 `ekb`、`keycloak` dump（`pg_restore`）。  
4. 恢复 MinIO 桶。  
5. 启动依赖与 migrate；`$DC up -d --build --wait`。  
6. `$DC exec backend python -m app.cli index rebuild`（或先 bootstrap + 按代次）。  
7. Keycloak 回调 / 管理员校验（`deployment-server.md` §4）。  
8. 验证清单见下。

完整命令：`docs/ops/backup-restore.md` §3。

---

## 4. 恢复验证

| 检查 | 方法 |
| --- | --- |
| API 健康 | `curl` `/health` `/ready` |
| 登录 | HTTPS 8443 OIDC |
| 抽样文档 | 预览/下载与备份前一致 |
| 检索 | 已知问题能命中；ACL 用户看不到无权库 |
| 问答 | 拒答与引用正常 |
| 开放 API | 旧 Key 行为符合吊销状态 |
| 审计 | 近期写操作可查 |

---

## 5. 单点与告警缺口

| 风险 | 状态 |
| --- | --- |
| 单机 compose / 宿主机 PG | 无自动 failover；评估后再上 HA |
| 备份与数据同盘 | 盘损可双丢；须异地副本 |
| Prometheus `alerts.yml` | 规则存在于 `deploy/observability`；**无 Alertmanager** |
| `prod.server.yml` | **无** observability profile |

建议告警：HTTP 5xx、队列积压、outbox 滞后、LLM 错误率、备份任务失败（需外接通知）。

---

## 6. 未完成的恢复演练

- [ ] 季度全量恢复到隔离环境并计时 RTO  
- [ ] 校验最近一次 dump 可读（`pg_restore -l`）自动化  
- [ ] 异地 MinIO/S3 拉通  
- [ ] WAL/PITR 演练到指定时间点  
- [ ] 仅索引损坏时的 rebuild 演练  

签署人 / 日期：____________（演练前保持空白）

---

## 7. 密钥与配置备份

- 环境文件、`directory_secret_key`、API pepper、MinIO/Keycloak 密码：进企业密钥库。  
- 轮换后旧预签名/水印签名立即失效（依赖 HMAC 密钥）。  
- 勿将真实 `.env.prod.server` 提交 Git。
