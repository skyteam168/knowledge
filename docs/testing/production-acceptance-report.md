# 生产验收测试报告（本阶段）

> 日期：2026-10-20  
> 环境：本地 docker compose（`127.0.0.1:3000` / Keycloak / OpenSearch）+ 单测夹具。  
> **未**对生产 Rocky 主机做恢复演练。

---

## 1. 真实栈验证（本轮）

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 重建镜像并就绪 | 通过 | `/ready` 全绿；`retention_deleted_document_days=30` |
| `index rebuild --strict` → v5 | 通过 | 37 docs / 1160 chunks；Qdrant=OS=PG |
| OpenSearch mapping `.en`/`.vi` | 通过 | `kb_chunks_v5` content.fields=`['en','vi']` |
| 中文站内搜索「发送邮件出错」 | 通过 | 命中 IT运维手册《发送邮件常见出错代码…》 |
| 英文站内搜索 `Style Line Overlay tolerance` | 通过 | 命中 HO26-GF-VAPOR 检验标准；snippet 含 EN/VI |
| OS `multi_match` 含 `title.en`/`content.en` | 通过 | top hit score≈26.9 → HO26 文档 |
| 软删超期 purge（造数 + `SoftDeletedDocumentPurger`） | 通过 | MinIO 对象删除、chunk=0、墓碑 `minio_key=""` |
| Gap 工作台页面 | 通过 | `/curation/gaps` 可打开（筛选/聚类控件可见） |
| 旧索引原地 PUT mapping | 预期失败→已修 | bootstrap 跳过缺分析器升级；需 rebuild（`495c869`） |

单测回归：`test_document_purge` / `test_retrieval_gold` / `test_index_backends` / `test_retention` → 14 passed。

---

## 2. 仍未覆盖

| 项 | 状态 |
| --- | --- |
| 全量 pytest / 前端 vitest | 未跑 |
| 生产备份恢复演练 / 异地副本 | 未做 |
| 越文专用分词插件 | 暂用 standard+lowercase |

---

## 3. 结论

本地真实栈上 **P1 多语 BM25 + 软删清理可用**。生产上线前务必：`index rebuild`、确认 retention 与备份窗口、推送含 `495c869` 的镜像。
