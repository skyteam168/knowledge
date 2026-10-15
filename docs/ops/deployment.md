# 生产部署（Docker Compose）

文件：`deploy/docker-compose.prod.yml`、`deploy/.env.prod.example`、`deploy/observability/`。

## 1. 镜像

| 镜像 | 构建 | 说明 |
|---|---|---|
| `backend` | `backend/Dockerfile` target `api`（默认） | uvicorn，`WEB_CONCURRENCY` 个进程；也用于一次性的 `migrate` |
| `backend-worker` | `backend/Dockerfile` target `worker` | dramatiq worker、outbox-dispatcher、scheduler |
| `frontend` | `frontend/Dockerfile` | nginx（非 root，监听 8080），静态资源 + `/api` 反向代理（SSE 不缓冲） |

共同点：多阶段构建、非 root 用户（uid 10001 / nginx）、`tini` 作为 PID 1、依赖由 `uv.lock` 锁定（`--frozen`）。可选构建参数 `INSTALL_DOCLING=true` 安装 Docling 版面解析模型。

CI 中构建并推送：

```bash
docker build -t $REGISTRY/backend:$TAG --target api backend
docker build -t $REGISTRY/backend-worker:$TAG --target worker backend
docker build -t $REGISTRY/frontend:$TAG --build-arg VITE_KEYCLOAK_URL=https://sso.example.com frontend
```

`VITE_KEYCLOAK_URL` 在构建时写入前端，换域名需要重新构建前端镜像。

## 2. 首次部署

```bash
cd deploy
cp .env.prod.example .env.prod             # 填写全部空值（openssl rand -hex 24）
grep ^METRICS_TOKEN= .env.prod | cut -d= -f2- > observability/metrics-token
DC="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$DC build                                  # 或 $DC pull（使用 CI 推送的镜像）
$DC up -d
$DC exec backend python -m app.cli index bootstrap   # 首次：创建活动索引代与别名
```

启动顺序由健康检查保证：存储 → keycloak → `migrate`（`alembic upgrade head`，成功后退出）→ backend → worker / dispatcher / scheduler → frontend。

在宿主机或负载均衡上配置 TLS 反向代理：

| 域名 | 转发到 |
|---|---|
| `PUBLIC_URL`（如 kb.example.com） | `127.0.0.1:${HTTP_PORT}`（frontend）；关闭代理缓冲以支持 SSE，读超时 ≥ 300s |
| `KEYCLOAK_PUBLIC_URL` | `127.0.0.1:8080`，转发 `X-Forwarded-*` |
| `MINIO_PUBLIC_ENDPOINT` | `127.0.0.1:9000`（浏览器通过预签名 URL 直传 / 预览），`client_max_body_size` ≥ `UPLOAD_MAX_BYTES` |

然后按 [Keycloak 对接 AD](keycloak-ad.md) 完成 realm 的生产配置。

## 3. 升级

```bash
$DC pull            # 或 build
$DC up -d           # migrate 先执行数据库迁移，再滚动重建应用容器
```

迁移只做向前兼容的变更；升级前先按 [备份与恢复](backup-restore.md) 做一次 PG 备份。涉及索引结构 / embedding 的版本说明中会注明是否需要 [索引重建](reindex.md)。

## 4. 容量与参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `WEB_CONCURRENCY` | 4 | API 进程数，约等于可用 CPU 核数 |
| `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` | 10 / 10 | 每个进程；总连接数 = (pool + overflow) × (API 进程 + worker 进程 + dispatcher + scheduler)，需小于 `POSTGRES_MAX_CONNECTIONS` 减去 Keycloak 的连接 |
| `WORKER_PROCESSES` / `WORKER_THREADS` | 2 / 4 | 解析、索引、评测任务的并发 |
| `LLM_MAX_CONNECTIONS` | 200 | 每进程到模型服务的连接上限；每个流式回答占用一个连接 |
| `EMBEDDING_BATCH_SIZE` / `EMBEDDING_CONCURRENCY` | 32 / 4 | 入库与重建时的 embedding 吞吐 |
| `RATE_LIMIT_*` | 见 `app/core/config.py` | 按用户 / 组织限流，问答与上传有单独的桶 |

压测结果与调优建议见 [压测报告](../perf/load-test-report.md)。

## 5. 可观测性（可选）

```bash
$DC --profile observability up -d
```

- Prometheus `127.0.0.1:9090`：抓取 backend `/metrics`（Bearer `METRICS_TOKEN`）、worker `:9191`、Keycloak；告警规则 `observability/alerts.yml`（错误率、慢请求、首 token、模型错误、队列 / outbox 积压）。
- Jaeger `127.0.0.1:16686`：设置 `OTEL_ENABLED=true` 后，API（FastAPI / SQLAlchemy / httpx）与 worker 的链路经 otel-collector 导出；collector 会删除 LLM span 上的提示词 / 回答内容。
- Grafana `127.0.0.1:3001`：已预置 Prometheus、Jaeger 数据源。
- Langfuse：设置 `LANGFUSE_HOST`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 后，模型调用 span 直接导出到 Langfuse（与 OTLP 导出相互独立）。

## 6. 可选组件

- 病毒扫描：`$DC --profile clamav up -d`，并设置 `VIRUS_SCAN_BACKEND=clamav`（ClamAV 首次启动需下载病毒库，约数分钟）。
- 敏感信息脱敏：`PII_MASK_ON_INGEST`（入库时脱敏 chunk 文本）、`PII_MASK_ON_OUTPUT`（回答与搜索结果输出时脱敏），类型由 `PII_TYPES` 配置。

## 7. 运维文档

- [备份与恢复](backup-restore.md)
- [索引重建与一致性修复](reindex.md)
- [更换 embedding 模型](embedding-migration.md)
- [Keycloak 对接 AD / LDAP](keycloak-ad.md)
