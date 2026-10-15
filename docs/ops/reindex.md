# 索引重建与一致性修复

Qdrant（向量）与 OpenSearch（全文）是从 PostgreSQL 派生的索引。写入链路：业务事务写 `outbox_events` → `outbox-dispatcher` 投递 → `worker` 幂等写入索引（以 `chunk_id + version` 为准）。所以索引出现问题时，**永远以 PG 为准修复索引**，不要反向修改 PG。

所有命令在后端容器内执行：

```bash
DC="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$DC exec backend python -m app.cli index --help
```

## 1. 索引代（generation）与别名

- 每一代索引包含一个 Qdrant collection 和一个 OpenSearch index，物理名为 `{INDEX_ALIAS}_v{N}`；读写都通过别名 `INDEX_ALIAS`（默认 `kb_chunks`）。
- 每一代记录它使用的 embedding 模型、维度和地址（`index_generations` 表），查询时按**当前活动代**的模型生成查询向量。
- 全量重建 = 建新一代 → 从 PG 写入全部数据 → 校验数量 → 原子切换别名，旧代保留以便回滚。构建期间新产生的变更同时写入新旧两代，切换前后不会丢数据，读请求全程不中断。

```bash
$DC exec backend python -m app.cli index generations     # 查看所有代及状态
```

管理端页面：管理 → 索引同步（Outbox 状态、死信重试、一致性校验与一键修复、索引代列表）。

## 2. 选择处理方式

| 现象 | 处理 |
|---|---|
| 个别文档搜不到 / 搜到已删除内容 | 对该知识库做一致性校验并修复（第 3 节） |
| Outbox 出现死信（dead） | 查看错误原因并修复依赖后，在“索引同步”页“重试全部死信” |
| Qdrant / OpenSearch 数据丢失或损坏 | 全量重建（第 4 节） |
| 修改了 OpenSearch mapping / 分词器（IK 词典除外） | 全量重建 |
| 只修改了同义词词典 | `index reload-synonyms`，无需重建（第 6 节） |
| 更换 embedding 模型或维度 | 见 [更换 embedding 模型](embedding-migration.md) |
| 修改了切分参数（`CHUNK_*`）或解析器 | 需要重新解析文档（第 5 节），重建索引不会改变 chunk |

## 3. 单个知识库：一致性校验与修复

校验比较 PG 中应被索引的 chunk 与 Qdrant / OpenSearch 中的实际条目（缺失、多余），正在处理中的文档会被跳过：

```bash
$DC exec backend python -m app.cli index check --kb <KB_ID>            # 只校验，不一致时退出码 1
$DC exec backend python -m app.cli index check --kb <KB_ID> --repair   # 重新写入缺失文档并删除多余条目
```

也可以在管理端“索引同步 → 一致性校验”中选择知识库执行，或调用 `POST /api/v1/admin/index/kbs/{kb_id}/check`、`/repair`。

## 4. 全量重建

```bash
# 1) 构建新一代并在校验通过后切换别名
$DC exec backend python -m app.cli index rebuild --strict

# 可选参数
#   --batch-size 100     每批读取的文档数
#   --no-activate        只构建不切换（切换前先人工验证）
#   --drop-old           切换成功后删除上一代的物理 collection / index（确认无需回滚后再用）
#   --strict             PG chunk 数、Qdrant 点数、OpenSearch 文档数不一致时中止并把新代标记为 failed
```

重建期间：

- 资源：embedding 调用量 = 全部 chunk 数，耗时主要取决于 embedding 服务吞吐（`EMBEDDING_BATCH_SIZE`、`EMBEDDING_CONCURRENCY`）。可先在低峰执行，必要时临时调高 embedding 服务副本数。
- 读请求继续使用旧代；新上传的文档同时写入两代。
- 失败时新代被标记为 `failed`，别名不变，可直接重试；用 `index drop <VERSION>` 清理失败代。

切换后验证：

```bash
$DC exec backend python -m app.cli index generations     # 新代为 active，stats 中三项数量一致
```

再在管理端运行一次离线评测，与切换前的基线对比 Recall / MRR。

### 回滚

旧代未删除时，可随时把别名指回旧代：

```bash
$DC exec backend python -m app.cli index activate <OLD_VERSION>
```

注意：回滚后，切换期间新增 / 修改的文档只写入了新代时，需要再对相关知识库执行一次 `check --repair`。

### 清理旧代

```bash
$DC exec backend python -m app.cli index drop <OLD_VERSION>
```

只能删除非活动代。建议观察 1~2 天、确认无需回滚后再删除。

## 5. 重新解析文档（切分参数 / 解析器变更）

全量重建只会把 PG 中已有的 chunk 重新写入索引。修改 `CHUNK_*` 参数、启用 OCR / Docling / MinerU 等变更需要重新解析：

- 单个文档：文档详情页“重新处理”，或 `POST /api/v1/documents/{document_id}/reprocess`。
- 批量：按知识库遍历文档调用上述接口（脚本示例）：

  ```python
  import httpx
  API, H = "https://kb.example.com/api/v1", {"Authorization": "Bearer <TOKEN>"}
  page = 1
  while True:
      docs = httpx.get(f"{API}/knowledge-bases/<KB_ID>/documents",
                       params={"page": page, "size": 100}, headers=H).json()
      for d in docs["items"]:
          httpx.post(f"{API}/documents/{d['id']}/reprocess", headers=H)
      if page * 100 >= docs["total"]:
          break
      page += 1
  ```

重新解析按文档逐个进行，新 chunk 写入后旧 chunk 的索引条目由 outbox 事件删除。注意接口限流（`RATE_LIMIT_*`），大批量处理时分批执行，并观察 `ekb_queue_backlog{queue="ingest"}`。

## 6. 同义词词典

编辑 `deploy/opensearch/analysis/synonyms.txt` 后（目录以只读方式挂载，容器内立即可见）：

```bash
$DC exec backend python -m app.cli index reload-synonyms
```

或在“索引同步”页点击“重新加载同义词”（平台管理员）。多节点 OpenSearch 需要把文件同步到每个节点。

## 7. 监控指标

- `ekb_outbox_events{status="pending|processing|dead"}`、`ekb_outbox_oldest_pending_seconds`：积压与卡住的事件。
- `ekb_queue_backlog{queue=...}`：worker 队列积压。
- 告警规则见 `deploy/observability/alerts.yml`（`EkbOutboxStuck`、`EkbOutboxDead`、`EkbQueueBacklog`）。
