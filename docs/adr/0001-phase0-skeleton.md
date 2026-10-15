# ADR-0001 阶段 0 工程骨架

- 状态：已接受
- 日期：2026-10-08

## 决策

1. **Monorepo**：`backend/`、`frontend/`、`deploy/`、`docs/` 同仓管理；`Makefile` 作为统一入口。
2. **后端依赖管理用 uv**，`uv.lock` 锁定版本；容器内 `uv sync --frozen --no-dev`。
3. **异步任务选 Dramatiq + Redis**（相比 Celery 更轻、API 简单）；测试环境（`APP_ENV=test`）自动切换 `StubBroker`。
4. **结构化日志**：标准库 logging + 自定义 JSON formatter；`TraceIdMiddleware`（纯 ASGI）读取/生成
   `X-Trace-ID`，写入 contextvar 与 `request.state`，并回写响应头。
5. **统一错误响应** `{code, message, detail, trace_id}`：`AppError` 体系 + HTTPException / 校验错误 / 未处理异常全局处理。
6. **就绪检查** `/ready`：并发检查 postgres、redis、minio、qdrant、opensearch、keycloak（必需）
   与 embedding、rerank、chat 模型服务（可选）。必需项失败返回 503 `not_ready`；仅可选项失败返回 200 `degraded`。
7. **OpenSearch 2.19.2 + IK 分词**：自定义镜像安装 `opensearch-analysis-ik`，版本需与 OpenSearch 严格一致。
   开发环境关闭安全插件。
8. **Keycloak 26** 使用同一 PostgreSQL 实例的独立数据库 `keycloak`，启动时导入 `realm-ekb.json`；
   `org_id` 通过 declarative user profile 声明为用户属性并映射到 token。
9. **Mock 模型服务**：确定性假数据（embedding 由文本哈希生成并归一化，维度默认 1024），支持流式 chat。

## 后续阶段预留（TODO）

- `app/llm/`：模型网关（超时、重试、降级）。
- `app/retrieval/`：混合检索与 ACL 前置过滤。
- 前端 Keycloak OIDC 登录、路由守卫；后端 JWT 校验。
- MinIO bucket 初始化、Outbox、审计日志与检索 trace 表。
