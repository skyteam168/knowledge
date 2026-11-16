# 备份恢复演练纪要（本机 compose）

> 日期：2026-11-14  
> 环境：`deploy/docker-compose.yml`（开发栈，`ekb-postgres-1`）  
> 对照：`docs/operations/backup-recovery.md`、`docs/ops/backup-restore.md`  
> 原则：**不破坏**生产/当前 `ekb` 库；恢复到临时库 `ekb_drill` 后删除。

---

## 1. 范围

| 项 | 本次 | 说明 |
| --- | --- | --- |
| PostgreSQL `ekb` | 已做 | `pg_dump -Fc` → `pg_restore` → 计数校验 |
| PostgreSQL `keycloak` | 已做 dump + `pg_restore -l` | 未整库 restore（避免干扰登录） |
| MinIO | **未做** | 开发栈无 `backup-minio` 挂载；生产见 `deploy/backup/minio-backup.sh` |
| 索引 rebuild | **未做** | 派生索引；全量 RTO 需另排窗口 |
| 异地副本 / PITR | **未做** | 已知差距，RPO≈日备 |

---

## 2. 步骤与耗时

| 步骤 | 命令摘要 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 1. Dump `ekb` | `pg_dump -U ekb -d ekb -Fc -Z 6 -f /tmp/ekb-drill.dump` | 约 **66.7 MiB**；`pg_restore -l` 可读（TOC≈418） | ~7s |
| 2. 建临时库 | `CREATE DATABASE ekb_drill OWNER ekb` | OK | <1s |
| 3. Restore | `pg_restore -U ekb -d ekb_drill --no-owner --role=ekb …` | OK | 计入合计 |
| 4. 冒烟计数 | `documents` / `chunks` / `terminology_entities` | **42 / 1384 / 23** | <1s |
| 5. 清理 | `DROP DATABASE ekb_drill` | OK | <1s |
| 6. Dump `keycloak` | `pg_dump … keycloak` + `pg_restore -l` | 约 **209 KiB**，列表可读 | <2s |
| **合计（restore 演练脚本）** | `deploy/backups/drill-20261114/run-restore-drill.sh` | `DRILL_OK` | **~20s** |

脚本路径：[`deploy/backups/drill-20261114/run-restore-drill.sh`](../../deploy/backups/drill-20261114/run-restore-drill.sh)（容器内执行；dump 文件在容器 `/tmp`，未强制落盘宿主机）。

---

## 3. 结论

| 指标 | 观察 |
| --- | --- |
| Dump 可读性 | 通过（`pg_restore -l`） |
| 逻辑恢复可行性 | 通过（临时库可查询业务表） |
| 本机 RTO（仅 PG 逻辑恢复到可查询） | **约 20 秒**（小库；不含应用启动与索引 rebuild） |
| 生产 RTO（含 MinIO + rebuild + 登录） | **仍 unverifiable**；需按 `backup-recovery.md` §3 在隔离环境做全量演练 |

**判定**：本机 **PG 逻辑备份/恢复通路可用**，可作为上线前最小验收。完整灾备（MinIO + 索引 + Keycloak 整库 + 计时 RTO≤4h）仍须季度隔离演练。

---

## 4. 后续动作

- [ ] 生产 `BACKUP_DIR` 异地同步抽检  
- [ ] MinIO mirror 一次 + 抽样对象对比  
- [ ] 隔离环境 `index rebuild --strict` 计时  
- [ ] 将本纪要勾进 `backup-recovery.md` §6 演练清单
