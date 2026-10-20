# 生产验收测试报告（本阶段）

> 日期：2026-10-20  
> 环境：本地 `backend/.venv` + SQLite 测试夹具（与 CI 同类）。  
> **未**在本机对生产 Rocky 主机执行恢复演练或全量 docker 回归。

---

## 1. 实际执行的命令与结果

```bash
cd backend
.venv/Scripts/python.exe -m pytest \
  tests/test_document_purge.py \
  tests/test_retrieval_gold.py \
  tests/test_index_backends.py \
  tests/test_retention.py -q
# 14 passed

.venv/Scripts/python.exe -m pytest -m gold -q
# gold gate green

.venv/Scripts/ruff.exe check <changed app/test files>
# All checks passed
```

| 套件 | 通过 | 失败 | 说明 |
| --- | --- | --- | --- |
| `test_document_purge` + retention | 含软删对象清理 | 0 | MinIO + chunk；墓碑保留 |
| `test_retrieval_gold` (`-m gold`) | 3 | 0 | JSONL 金标门禁 + 多语 sparse 字段 |
| `test_index_backends` OpenSearch mapping | 含 `.en`/`.vi` | 0 | 分析器断言 |
| 全量 pytest | — | — | **本阶段未完整跑完** → `unverifiable` |
| 前端 vitest | — | — | **未执行** |
| 生产备份恢复演练 | — | — | **未执行** |

---

## 2. 安全 / 运维相关（本阶段）

| 项 | 结果 |
| --- | --- |
| 软删超期 MinIO / chunk 清理 | 通过；默认 30 天；可选硬删行 |
| 多语 BM25 mapping | 代码落地；**生产需 `index rebuild`** |
| 金标门禁 | 单元门禁通过；线上召回仍依赖真实索引评测 |
| 过期 / 草稿文档不进 hydrate | 前期 P0 已测 |

---

## 3. 是否建议进入生产试运行

**有条件建议**：单组织内网试运行可以，须先：

1. `alembic upgrade head`（含 lifecycle / gap SLA 迁移）  
2. OpenSearch **全量 rebuild**（多语 multi-field）  
3. 确认 `RETENTION_DELETED_DOCUMENT_DAYS` 与备份窗口协调（见 `docs/ops/backup-restore.md`）  
4. 备份异地与告警仍为待办（见 `docs/operations/backup-recovery.md`）

正式多工厂 / 强制审核制度库上线前，完成全量 pytest、vitest、备份演练。
