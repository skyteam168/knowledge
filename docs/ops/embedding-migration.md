# 更换 embedding 模型

向量与模型强绑定：换模型（或换维度）后，旧向量与新查询向量不可比，必须**全量重新生成向量**。系统用“索引代”实现零停机切换：

- 每一代索引记录自己的 embedding 模型、维度和服务地址（`index_generations` 表）。
- 查询时按**当前活动代**记录的模型生成查询向量，所以切换别名的同时查询侧自动换用新模型，不存在“新查询向量 + 旧索引”的错配窗口。
- 重建期间新上传 / 修改的文档同时写入新旧两代（各自用自己的模型），读请求继续走旧代。
- 旧代保留到确认无需回滚为止，回滚只需切回别名。

## 1. 准备

1. **部署新模型服务**（TEI / vLLM 等 OpenAI 兼容接口），与旧服务并存。以 Qwen3-Embedding 为例：

   ```bash
   docker run -d --gpus all -p 8081:80 ghcr.io/huggingface/text-embeddings-inference:1.7 \
     --model-id Qwen/Qwen3-Embedding-4B
   ```

2. **确认接口与维度**（在后端容器内调用，保证网络可达）：

   ```bash
   $DC exec backend python - <<'EOF'
   import httpx
   r = httpx.post("http://tei-embedding-new:80/v1/embeddings",
                  json={"model": "Qwen/Qwen3-Embedding-4B", "input": ["测试"]}, timeout=30)
   r.raise_for_status(); print(len(r.json()["data"][0]["embedding"]))
   EOF
   ```

   Matryoshka 模型（Qwen3-Embedding）可以截断到较小维度：设置 `EMBEDDING_SEND_DIMENSIONS=true`，并在下面的 `--embedding-dim` 中指定目标维度。

3. **记录基线**：管理 → 离线评测，用回归评测集对当前检索策略运行一次评测（建议开启 LLM 评判），记下任务 ID。评测记录的“运行环境”中会保存当前索引代和 embedding 模型。

4. **评估容量与耗时**：

   - 重建会对全部 chunk 调用一次 embedding（数量见 `python -m app.cli index generations` 中当前代的 `stats.chunks`）。
   - 耗时 ≈ chunk 数 / embedding 服务吞吐。吞吐受 `EMBEDDING_BATCH_SIZE`（单次请求条数，默认 32）与 `EMBEDDING_CONCURRENCY`（并发请求数，默认 4）影响，可根据模型服务的 `max-batch-tokens` / 显存适当调高。
   - Qdrant 磁盘与内存需求随维度线性增长；重建期间新旧两代同时存在，需预留双倍空间。

## 2. 构建新一代并切换

```bash
DC="docker compose -f docker-compose.prod.yml --env-file .env.prod"

$DC exec backend python -m app.cli index rebuild \
  --embedding-model Qwen/Qwen3-Embedding-4B \
  --embedding-dim 2560 \
  --embedding-base-url http://tei-embedding-new:80/v1 \
  --strict
```

- 进度打印到 stderr（已处理文档数 / chunk 数）；建议在 `tmux` / `screen` 中执行。
- `--strict`：PG chunk 数、Qdrant 点数、OpenSearch 文档数任一不一致即中止，新代标记为 `failed`，别名保持不变。
- 想先人工验证再切换：加 `--no-activate`，验证后执行 `python -m app.cli index activate <NEW_VERSION>`。注意未激活的新代无法通过离线评测验证（评测总是使用活动代），通常直接切换并用第 3 节的方式验证、必要时回滚。

## 3. 验证

1. `python -m app.cli index generations`：新代为 `active`，`embedding_model` / `embedding_dim` 正确，`stats` 中三项数量一致。
2. 管理 → 离线评测：用**同一评测集、同一检索策略**再运行一次，然后在“对比所选”中对比基线：
   - 配置差异中会显示 `environment.index_generation`、`environment.embedding_model` 的变化；
   - 重点看 Recall@5/10、MRR、nDCG 及“逐用例对比”中变差的用例。
3. 新模型改变的是召回集合，rerank 分数仍由 rerank 模型给出；但召回质量变化会影响证据判定。观察拒答率（分析 → 质量）是否异常，必要时调整检索策略（召回 top_k、RRF 参数）或证据阈值（`CHAT_EVIDENCE_MIN_SCORE`、`CHAT_EVIDENCE_CONFIDENT_SCORE`）后再评测对比。
4. 分析 → 性能：检索阶段 P50/P95 是否在预期内（维度变大，向量检索耗时会增加）。

## 4. 收尾

1. 更新 `.env.prod` 中的 `EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_DIM`（和 `EMBEDDING_SEND_DIMENSIONS`），然后 `$DC up -d`。这些配置用于以后的 `index bootstrap` / `rebuild` 默认值与健康检查；运行中的检索与写入已经按活动代的记录使用新模型。
2. 观察 1~2 天，确认无需回滚后删除旧代并下线旧模型服务：

   ```bash
   $DC exec backend python -m app.cli index drop <OLD_VERSION>
   ```

## 5. 回滚

旧代和旧模型服务仍在时：

```bash
$DC exec backend python -m app.cli index activate <OLD_VERSION>
```

查询立即换回旧模型。切换期间写入的数据在新旧两代中都有，通常无需额外处理；若有疑问，对相关知识库执行 `python -m app.cli index check --kb <KB_ID> --repair`。

## 6. 常见问题

| 问题 | 处理 |
|---|---|
| 重建报 `count mismatch` | 有文档在重建过程中处理失败。查看 worker 日志与“索引同步”页的死信，修复后重新执行 rebuild |
| embedding 请求超时 / 429 | 降低 `EMBEDDING_CONCURRENCY` 或提高模型服务副本数；超时时间 `EMBEDDING_TIMEOUT_SECONDS` |
| 切换后部分查询无结果 | 检查查询侧能否访问新模型地址（就绪检查 `/ready` 中的 embedding 项）；必要时先回滚 |
| 只想调整 rerank 模型 / LLM | 不需要重建索引，修改 `RERANK_*` / `CHAT_*` 后重启 backend、worker 即可；同样建议前后各跑一次离线评测对比 |
