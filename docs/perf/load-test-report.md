# 问答接口压测报告

日期：2026-10-08　脚本：`backend/loadtest/locustfile.py`　原始数据：locust `--csv` 输出（`u50/u100/u200`、`w4_u100/w4_u200`）

## 1. 结论

| 项 | 结论 |
|---|---|
| 正确性 | 所有轮次 0 失败（HTTP 与 SSE 事件），限流、ACL、trace 写入均在压测期间正常工作 |
| 单进程容量 | 1 个 uvicorn 进程约 **45–50 req/s**（其中问答约 9–10 条/s）；超过约 50 并发用户后吞吐不再增长，延迟线性上升 |
| 水平扩展 | `WEB_CONCURRENCY=4` 时 100 用户吞吐 **83 req/s**（+67%），首 token P95 从 4.7s 降到 1.0s；200 用户 107 req/s |
| 瓶颈 | API 进程的事件循环（JSON 序列化、鉴权、检索结果组装），而非 PG / Qdrant / OpenSearch（压测期间 PG CPU < 16%） |
| 缓存 | 检索结果缓存命中率 **92.8%**，查询向量缓存命中率 **96.5%**（问题集重复度高，生产会更低） |
| 配置 | 连接池、embedding 批量、rerank 并发、缓存 TTL 均合理；LLM 连接池改为可配置（原为硬编码 100）；生产默认 `WEB_CONCURRENCY=4` |

## 2. 环境与方法

| 项 | 值 |
|---|---|
| 主机 | Intel i7-13700（16 线程分配给 Docker）、32 GB，Docker Desktop 29.8 / WSL2 |
| 部署 | `deploy/docker-compose.yml` 全套服务（PG 16、Redis 7、Qdrant、OpenSearch 2.x、MinIO、Keycloak） |
| 模型 | **mock-llm**（OpenAI 兼容）：embedding / rerank 即时返回，chat 流式输出每字符 20ms |
| 数据 | 15 篇已索引文档、147 个 chunk，用户 alice / bob / carol（不同 org/group，ACL 前置过滤生效） |
| 压测机 | `locustio/locust:2.32.0` 容器，与后端同一 docker 网络（`--host http://backend:8000`），单进程 |
| 限流 | 压测时通过 override 把 `RATE_LIMIT_*` 调到不触发；默认配置下单用户 20 次问答/分钟会被限流（429） |

用户行为（`KnowledgeUser`，思考时间 1–3s）：

| 任务 | 权重 | 内容 |
|---|---|---|
| `ask` | 5 | `POST /chat/conversations/{id}/messages`，完整读取 SSE 流；每 `EKB_NEW_CONVERSATION_EVERY` 轮新建会话（多轮改写） |
| `search` | 3 | `GET /search?q=…&top_k=10` |
| `conversations` | 1 | `GET /chat/conversations` |

自定义 SSE 指标：`chat: first token`（请求发出到第一个 token）、`chat: complete`（到 `done` 事件）、`chat: <grounding>`（按回答类型 grounded / uncertain / no_evidence 分组的总耗时）。

## 3. 结果

### 3.1 单进程（`--workers 1`，开发 compose 默认）

| 并发用户 | 时长 | 请求数 | 失败 | 吞吐 req/s | 问答 条/s | 首 token P50 / P95 / P99 | 完整回答 P50 / P95 | 搜索 P50 / P95 | 会话列表 P95 |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 40s | — | 0 | — | — | 48ms / — / — | 2.8s / — | — | — |
| 50 | 180s | 7 908 | 0 | 44.0 | 8.7 | 48ms / 530ms / 780ms | 2.9s / 4.2s | 27ms / 270ms | 230ms |
| 100 | 180s | 8 926 | 0 | 49.7 | 9.8 | 3.1s / 4.7s / 5.5s | 5.2s / 7.7s | 1.3s / 2.4s | 2.4s |
| 200 | 150s | 7 149 | 0 | 47.8 | 9.4 | 10s / 13s / 15s | 12s / 16s | 4.1s / 6.2s | 6.2s |

10 用户为冒烟轮，仅记录了中位数。

### 3.2 四进程（`--workers 4`）

| 并发用户 | 时长 | 请求数 | 失败 | 吞吐 req/s | 问答 条/s | 首 token P50 / P95 / P99 | 完整回答 P50 / P95 | 搜索 P50 / P95 | 会话列表 P95 |
|---|---|---|---|---|---|---|---|---|---|
| 100 | 150s | 12 368 | 0 | 82.7 | 16.5 | 42ms / 1.0s / 1.6s | 2.9s / 4.2s | 21ms / 560ms | 550ms |
| 200 | 150s | 16 071 | 0 | 107.4 | 21.2 | 63ms / 6.6s / 8.2s | 3.3s / 9.5s | 34ms / 3.8s | 3.8s |

200 用户四进程时延迟呈双峰（P50 63ms、P66 3.9s）：一部分请求排队。此时单进程 locust 自身也接近 CPU 上限，结果偏保守；更高并发需用 locust 分布式模式（`--master` / `--worker`）复测。

### 3.3 回答类型耗时（50 用户，单进程）

| 类型 | 数量 | P50 | P95 | 说明 |
|---|---|---|---|---|
| no_evidence | 628 | 54ms | 550ms | 检索无证据时直接拒答，不调用 LLM |
| uncertain | 468 | 2.9s | 3.4s | 低置信回答（mock 输出较短） |
| grounded | 473 | 3.2s | 4.4s | 完整带引用回答；耗时主要来自 mock 的逐字流式延迟 |

### 3.4 资源（`docker stats`，12s 采样）

| 容器 | 50 用户 | 100 用户 | 备注 |
|---|---|---|---|
| backend（1 进程） | 40–55% | 25–75% | 单进程 Python 最多用满约 1 核，CPU 曲线随事件循环排队波动 |
| backend（4 进程） | — | 未饱和 | 吞吐随进程数提升，说明单进程是瓶颈 |
| postgres | 5–15% | 5–16% | 每个问答写 trace / 消息 / 审计；连接池无排队超时 |
| mock-llm | 5–13% | 5–13% | — |
| qdrant / opensearch / redis | < 3% | < 3% | 检索结果缓存命中后不访问索引 |

后端内存稳定在 140–160 MiB / 进程，压测过程中无增长。

### 3.5 缓存与模型调用（Prometheus，全部轮次累计）

| 指标 | 值 |
|---|---|
| `ekb_cache_lookups_total{cache="retrieval_result"}` | hit 7 346 / miss 567（**92.8%**） |
| `ekb_cache_lookups_total{cache="query_embedding"}` | hit 547 / miss 20（**96.5%**） |
| `ekb_llm_calls_total{kind="chat_stream"}` | ok 2 991 / error 60 |
| `ekb_llm_calls_total{kind="rerank"}` | ok 1 701 |

60 个 `chat_stream` error 全部发生在 100 / 200 用户轮次结束的同一秒：locust 停止时主动断开进行中的 SSE 连接，服务端取消生成并回收数据库连接（日志 `CancelledError ... terminating connection`），不是服务端错误。

Analytics 看板（`/analytics`，压测后重新汇总）显示的同期阶段耗时与 locust 一致：检索 P50 26ms / P95 2.4s（含排队），rerank 缓存命中后可忽略，总耗时 P50 2.9s / P95 7.0s。

## 4. 配置复核

### 4.1 数据库连接池

- 每进程 `DATABASE_POOL_SIZE=10` + `DATABASE_MAX_OVERFLOW=10`，`pool_timeout=10s`，`pool_recycle=1800s`。
- 请求级会话使用 `Depends(get_db_session, scope="function")`，在响应开始流式输出前就归还连接；SSE 生成过程只在写入消息 / trace 时短暂占用连接，流式输出期间不持有连接。因此并发 SSE 数不受连接池限制，压测中未出现池等待超时。
- 总连接数估算：`(pool + overflow) × (WEB_CONCURRENCY + WORKER_PROCESSES + 2)`。生产默认 `20 × (4 + 2 + 2) = 160`，PG `max_connections=300`，为 Keycloak 和运维留有余量。扩容 API 进程时同步检查该公式。

### 4.2 模型调用

| 项 | 默认 | 评估 |
|---|---|---|
| LLM HTTP 连接池 | `LLM_MAX_CONNECTIONS=200`、keepalive 50、`LLM_POOL_TIMEOUT_SECONDS=10` | 原先硬编码 100；每个流式回答占用一个连接，单进程 100 并发流即会排队。现可配置，并在池满时 10s 快速失败（走降级），而不是等满 60s 读超时 |
| Embedding | `EMBEDDING_BATCH_SIZE=32`、`EMBEDDING_CONCURRENCY=4`、超时 60s | 与 TEI 默认 `max_client_batch_size=32` 一致；查询侧单条且命中缓存率高，批量参数只影响入库 / 重建吞吐 |
| Rerank | `top_n=40`、`batch_size=16`、`concurrency=4`、超时 8s、`max_chars=2000` | 40 候选 → 3 个批次并行，一次往返完成；超时后降级为融合分排序（trace 中记 `degraded`），不会拖垮首 token |
| Chat | 超时 60s；改写超时 15s | 流式回答由首 token 指标监控（告警 `EkbSlowFirstToken`） |

### 4.3 缓存

| 缓存 | TTL | key 包含 | 评估 |
|---|---|---|---|
| 查询向量 | 7 天 | 模型名 + 维度 + 服务地址 + 文本 | 与权限无关，可长期缓存；换 embedding 模型后 key 自然失效 |
| 检索结果（含 rerank 分数） | 60s | query + profile + 知识库 + **权限范围**（org / groups / roles） + 索引代 | 满足"缓存 key 包含权限范围"；60s 内的文档 ACL 变更由回答前的 PG 二次校验兜底 |
| 鉴权（JWKS / 权限） | 600s | — | 权限变更通过事件主动失效（ACL 回归测试覆盖） |

压测命中率偏高是因为问题集只有 20 条；生产中热门问题集中度通常在 30–60%，仍能明显降低 rerank 负载。

### 4.4 限流

默认 300 次/用户/分钟（问答 20 次）、3 000 次/组织/分钟（问答 300 次）。按上面的单进程容量（约 9–10 条问答/s ≈ 570 条/分钟），4 进程部署可以承受约 7 个组织同时打满问答限额；组织规模更大时应提高 `WEB_CONCURRENCY` 或调整 `RATE_LIMIT_CHAT_ORG_REQUESTS`。

## 5. 建议

1. 生产 `WEB_CONCURRENCY` 取可用 CPU 核数（默认 4）；单机核数不够时横向扩 backend 副本，它们是无状态的（限流、缓存都在 Redis）。
2. 按 4.1 的公式同步调整 `POSTGRES_MAX_CONNECTIONS`；副本较多时在 PG 前加 PgBouncer（transaction 模式）。
3. 每个 API 进程的 `LLM_MAX_CONNECTIONS` 需 ≥ 预期并发流数；vLLM 侧按 `--max-num-seqs` 规划，网关侧的池满快速失败避免请求堆积。
4. 用真实模型复测：mock 下首 token ≈ 检索 + 改写耗时，真实 LLM 会再增加 prefill 时间（Qwen3-32B / 8k 上下文通常 0.3–1s），完整回答时长取决于输出长度和 GPU 吞吐。容量规划以 GPU 侧 tokens/s 为准，API 层按本报告约 10 条问答/s/进程估算。
5. 压测前务必放开或调高 `RATE_LIMIT_*`（或使用更多测试账号），否则测到的是限流而不是系统容量。

## 6. 复现

```bash
# 与后端同一网络（推荐，避免宿主端口冲突）
docker run --rm --network ekb_default \
  -v $PWD/backend/loadtest:/mnt/locust -v $PWD/out:/out \
  -e EKB_TOKEN_URL=http://keycloak:8080/realms/ekb/protocol/openid-connect/token \
  locustio/locust:2.32.0 -f /mnt/locust/locustfile.py --host http://backend:8000 \
  --headless -u 100 -r 10 -t 180s --only-summary --csv /out/u100

# 或在本机
cd backend
uv sync --group loadtest
EKB_TOKEN_URL=http://localhost:8080/realms/ekb/protocol/openid-connect/token \
  uv run --group loadtest locust -f loadtest/locustfile.py --host http://localhost:8000
```

可用环境变量：`EKB_TOKEN_URL`、`EKB_CLIENT_ID`（默认 `ekb-frontend`）、`EKB_USERS`（`user:password,…`）、`EKB_TOKEN`（直接使用固定 token）、`EKB_KB_IDS`、`EKB_QUESTIONS`（问题文件，每行一条）、`EKB_NEW_CONVERSATION_EVERY`。

调高限流的 compose override 示例：

```yaml
services:
  backend:
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
    environment:
      RATE_LIMIT_USER_REQUESTS: "100000"
      RATE_LIMIT_ORG_REQUESTS: "1000000"
      RATE_LIMIT_CHAT_USER_REQUESTS: "100000"
      RATE_LIMIT_CHAT_ORG_REQUESTS: "1000000"
```
