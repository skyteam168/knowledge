# 备份与恢复

## 1. 备份范围

| 组件 | 内容 | 是否必须备份 | 说明 |
|---|---|---|---|
| PostgreSQL `ekb` 库 | 全部业务数据（知识库、文档元数据、chunk、ACL、问答记录、trace、审计、评测、分析汇总） | **必须** | 唯一真相源 |
| PostgreSQL `keycloak` 库 | 用户、角色、客户端、AD 联邦配置 | **必须** | 与 `ekb` 库同实例 |
| MinIO `ekb-documents` 桶 | 原始上传文件 | **必须** | 重新解析 / 预览 / 下载依赖原文件 |
| Qdrant / OpenSearch | 向量索引、全文索引 | 可选 | 派生索引，可从 PG 全量重建；快照只用于缩短恢复时间（RTO） |
| Redis | 任务队列、缓存、限流计数 | 不需要 | 恢复后未完成的任务由 outbox 重新投递；缓存自动重建 |
| `deploy/.env.prod`、`observability/metrics-token`、Keycloak realm 导出 | 配置与密钥 | **必须** | 存放到密钥管理系统，不要与数据备份放在同一位置 |

> 架构约定：PG + MinIO 是完整状态，Qdrant / OpenSearch 任何时候都可以用 `python -m app.cli index rebuild` 从 PG 重建。

建议策略：PG 每日全量 + WAL 归档（PITR，RPO ≤ 15 分钟）；MinIO 每日增量镜像到异地；索引快照每周一次。

以下命令均在 `deploy/` 目录执行，`DC` 代表：

```bash
DC="docker compose -f docker-compose.prod.yml --env-file .env.prod"
```

## 2. 备份

### 2.1 PostgreSQL

逻辑备份（custom 格式，可并行恢复、可单表恢复）：

```bash
TS=$(date +%Y%m%d-%H%M%S)
for db in ekb keycloak; do
  $DC exec -T postgres sh -c "pg_dump -U \$POSTGRES_USER -d $db -Fc -Z 6 -f /backups/$db-$TS.dump"
done
# 校验备份可读
$DC exec -T postgres pg_restore -l /backups/ekb-$TS.dump > /dev/null && echo OK
```

`/backups` 挂载自宿主机 `${BACKUP_DIR}`（默认 `deploy/backups/`），请再同步到异地存储并按保留策略（例如日备 14 天、月备 12 个月）清理。

需要时间点恢复（PITR）时，改用 `pg_basebackup` + WAL 归档（`archive_mode=on`、`archive_command` 推送到对象存储），或使用 pgBackRest / WAL-G；逻辑备份仍保留作为第二道保障。

### 2.2 MinIO

使用 MinIO Client（`mc`）镜像到备份端（另一套 MinIO / S3 / NAS）：

```bash
docker run --rm --network ekb-prod_default -v "$PWD/backups/minio:/backup" minio/mc sh -c "
  mc alias set src http://minio:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD &&
  mc mirror --overwrite --preserve src/ekb-documents /backup/ekb-documents"
```

（需通过 `-e MINIO_ROOT_USER=... -e MINIO_ROOT_PASSWORD=...` 传入凭据。）对象写入后不会被修改（文档新版本使用新 key），增量镜像即可；开启桶版本控制可防误删。

### 2.3 索引快照（可选）

Qdrant（快照落在 `${BACKUP_DIR}/qdrant`）：

```bash
COLL=$($DC exec -T backend python -m app.cli index generations | python -c "import json,sys;print([g for g in json.load(sys.stdin) if g['status']=='active'][0]['qdrant_collection'])")
$DC exec -T backend python - <<EOF
import httpx, os
r = httpx.post(f"http://qdrant:6333/collections/$COLL/snapshots",
               headers={"api-key": os.environ["QDRANT_API_KEY"]}, timeout=600)
print(r.status_code, r.text)
EOF
```

OpenSearch（快照仓库目录 `${BACKUP_DIR}/opensearch`，`path.repo` 已在 compose 中配置）：

```bash
$DC exec -T opensearch curl -s -XPUT localhost:9200/_snapshot/ekb -H 'Content-Type: application/json' \
  -d '{"type":"fs","settings":{"location":"/usr/share/opensearch/snapshots"}}'
$DC exec -T opensearch curl -s -XPUT "localhost:9200/_snapshot/ekb/snap-$(date +%Y%m%d)?wait_for_completion=true"
```

## 3. 恢复

### 3.1 全量恢复（新环境或灾难恢复）

1. 准备配置：恢复 `.env.prod`、`observability/metrics-token`。
2. 只启动存储：

   ```bash
   $DC up -d postgres redis minio qdrant opensearch
   ```

3. 恢复 PostgreSQL（`ekb` 与 `keycloak`；init 脚本已创建空库）：

   ```bash
   for db in ekb keycloak; do
     $DC exec -T postgres sh -c "pg_restore -U \$POSTGRES_USER -d $db --clean --if-exists --no-owner -j 4 /backups/$db-<TS>.dump"
   done
   ```

4. 恢复 MinIO 对象：

   ```bash
   docker run --rm --network ekb-prod_default -v "$PWD/backups/minio:/backup" \
     -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD minio/mc sh -c "
     mc alias set dst http://minio:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD &&
     mc mb -p dst/ekb-documents && mc mirror --overwrite /backup/ekb-documents dst/ekb-documents"
   ```

5. 启动应用（`migrate` 会把库升级到当前版本）：

   ```bash
   $DC up -d
   ```

6. 重建检索索引（二选一）：
   - **从 PG 重建**（推荐，结果一定与 PG 一致）：

     ```bash
     $DC exec backend python -m app.cli index rebuild --strict --drop-old
     ```

   - **恢复索引快照**（更快）：先恢复 Qdrant / OpenSearch 快照，再对每个知识库执行一致性校验与修复，补齐快照之后的变化：

     ```bash
     $DC exec backend python -m app.cli index check --kb <KB_ID> --repair
     ```

7. 验证：见第 4 节。

### 3.2 单个文档 / 知识库误删

知识库和文档的删除是软删除（`deleted_at`）+ outbox 事件（删除索引条目）。PG 中记录还在时，清空 `deleted_at` 后执行第 4 步即可；记录已被清理时：

1. 把备份恢复到临时库：`createdb ekb_restore && pg_restore -d ekb_restore ...`。
2. 从临时库导出相关行（`knowledge_bases`、`documents`、`document_versions`、`chunks`、`resource_acl` 等，按 `kb_id` / `document_id` 过滤），导入生产库。
3. 确认 MinIO 中原文件仍在（或从镜像恢复对应对象）。
4. `python -m app.cli index check --kb <KB_ID> --repair` 重新写入索引。

### 3.3 Keycloak 配置回滚

只回滚 Keycloak 时，恢复 `keycloak` 库即可（停止 keycloak 容器后执行 3.1 第 3 步中针对 `keycloak` 的命令），业务库不受影响。也可以在管理台导出 / 导入 realm（Realm settings → Action → Partial export / import）。

## 4. 恢复后验证清单

- `curl https://<PUBLIC_URL>/ready` 返回 `ready`，各依赖 `up`。
- `python -m app.cli index generations`：有且只有一个 `active` 代。
- 管理 → 索引同步：Outbox 无死信；对重点知识库执行“一致性校验”结果一致。
- 抽查：登录、知识库列表、文档预览 / 下载（MinIO）、搜索、AI 助手问答（含引用）。
- 管理 → 审计日志可查询到恢复前的记录。
- 运行一次离线评测（管理 → 离线评测），与恢复前的基线指标对比无明显回退。

## 5. 演练

每季度在隔离环境做一次完整恢复演练，记录实际 RPO / RTO，并更新本文档。
