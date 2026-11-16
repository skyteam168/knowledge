# ADR 0003：单机 HA 分阶段评估（不做假 HA）

- 状态：已采纳（2026-11-14）
- 关联：TASK D4；`docs/system-overview.md` §11.2；压测 [`docs/perf/load-test-report.md`](../perf/load-test-report.md)

## 背景

当前生产形态是**单机 Docker Compose**（或宿主机 PG/Redis + 容器应用）。`restart: unless-stopped`、多进程 `WEB_CONCURRENCY`、备份演练与告警门禁已具备，但**任一台宿主机故障 = 全停**。300 人左右内部使用时，数小时 RTO（备份恢复）通常可接受；对外宣称「高可用」则不可接受。

本 ADR 明确：**不把单机 compose 包装成 HA**；给出可交付的阶段划分与阶段 1（API 无状态水平扩展）示例。

## 决策

### 不做

| 做法 | 原因 |
| --- | --- |
| 单机双容器互称「主备 HA」 | 共享同一磁盘 / 同一内核，无独立故障域 |
| 未验证的自动 failover 脚本当验收 | 假 HA；缺演练与脑裂对策 |
| 多副本 `outbox-dispatcher` / `scheduler` | claim / 周期任务需单写者；多实例会竞态或重复调度 |
| 本阶段落地 PG 流复制 + Redis Sentinel + MinIO 纠删 | 运维面过大，超出「阶段性产物」范围 |

### 阶段划分

| 阶段 | 目标 | 故障域 | 交付物 |
| --- | --- | --- | --- |
| **0 现状** | 可恢复单机 | 主机宕机 → 停服，靠备份恢复 | D1 演练纪要、D2 告警门禁、暴露面清单 |
| **1 API 水平扩展** | 吞吐 / 单进程故障隔离 | 仍单机；一个 API 容器挂了仍可服务 | 本仓库 `deploy/docker-compose.ha-api.yml` + `nginx/frontend-ha.conf` |
| **2 双机主备（评估）** | 主机级 RTO 缩短 | 主机 A 挂 → 切 B | 见下「双机评估」；**本板不实现** |
| **3 多活** | 区域级 | 超出当前组织规模需求 | 搁置（TASK E） |

### 组件可扩展性（阶段 1 约束）

| 组件 | 多副本？ | 说明 |
| --- | --- | --- |
| `backend`（API） | **可以** | 无会话粘滞要求（JWT）；限流 / 缓存在 Redis；SSE 单连接粘在一个 upstream |
| `frontend` | 可以 | 静态 + 反代；阶段 1 用其 nginx 做 API 负载均衡即可 |
| `worker`（dramatiq） | 可以（谨慎） | broker 天然多消费；注意 PG 连接与 CPU；阶段 1 不强制扩 |
| `outbox-dispatcher` | **保持 1** | outbox claim 单写者 |
| `scheduler` | **保持 1** | 周期任务入口 |
| PostgreSQL / Redis / MinIO / Qdrant / OpenSearch / Keycloak | 阶段 1 不扩 | 真相源与派生索引的 HA 属阶段 2+ |

### 双机主备评估（阶段 2，仅结论）

若业务要求「单机房一台挂了仍分钟级恢复」，优先顺序：

1. **虚机 / 裸机主备 + 共享或复制存储**：PG 流复制（同步或准同步）+ 定期 failover 演练；Redis 主从或托管；MinIO 双节点或把对象放到已有企业对象存储。  
2. **应用层**：两台均部署 `backend`/`worker`/`frontend`，VIP 或 DNS 切到备机；**dispatcher/scheduler 仅在主上跑**（或用分布式锁选举，需另立 ADR）。  
3. **索引**：Qdrant / OpenSearch 可从 PG+MinIO 重建；备机可冷备或异步跟，RPO 允许时不必强同步。  
4. **Keycloak**：与业务库同等对待（独立库备份 / 复制），登录不可用则整站不可用。

在未完成「故障注入演练 + 文档化 RTO/RPO」前，不得在对外材料写「已高可用」。

## 阶段 1 用法（可选）

```bash
cd deploy
docker compose -f docker-compose.prod.yml -f docker-compose.ha-api.yml \
  --env-file .env.prod up -d --scale backend=2
```

- `frontend-ha.conf`：Docker 内嵌 DNS `127.0.0.11` + 变量 `proxy_pass`，避免 nginx 启动时钉死单一 backend IP。  
- 扩 API 后同步下调单容器 `WEB_CONCURRENCY` 或上调 `POSTGRES_MAX_CONNECTIONS` / PgBouncer（见压测报告 §5）。  
- `OIDC_BRIDGE_INTERNAL_URL` 可暂指 `http://backend:8000`（Docker DNS 会在副本间轮询）；若需固定桥接实例，再单独加服务名。

## 后果

- 文档与销售口径：单机 = 可恢复，≠ HA。  
- 需要更高可用时按阶段 2 立项，而不是继续堆同机容器。  
- TASK「多工厂强隔离」仍排在本 ADR 阶段 2 之后评估。
