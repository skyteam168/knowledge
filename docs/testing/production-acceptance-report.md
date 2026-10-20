# 生产验收测试报告（本阶段）

> 日期：2026-10-20  
> 环境：本地 `backend/.venv` + SQLite 测试夹具（与 CI 同类）。  
> **未**在本机对生产 Rocky 主机执行恢复演练或全量 docker 回归。

---

## 1. 实际执行的命令与结果

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_document_lifecycle.py -q
# 3 passed

.venv/Scripts/python.exe -m pytest \
  tests/test_document_lifecycle.py \
  tests/test_document_protection.py \
  tests/test_search_acl.py \
  tests/test_acl_regression.py \
  tests/test_document_versions.py \
  tests/test_open_api.py -q
# 39 passed

.venv/Scripts/ruff.exe check <changed app files>
# All checks passed
```

| 套件 | 通过 | 失败 | 说明 |
| --- | --- | --- | --- |
| `test_document_lifecycle` | 3 | 0 | 生效窗口、状态机、hydrate 过滤 |
| 保护 / ACL / 版本 / Open API 回归 | 36 | 0 | 与上表合计 39 |
| 全量 pytest (~369) | — | — | **本阶段未完整跑完** → `unverifiable` |
| 前端 vitest | — | — | **未执行** |
| 生产备份恢复演练 | — | — | **未执行** |

---

## 2. 安全相关（本阶段）

| 项 | 结果 |
| --- | --- |
| 过期 / 草稿文档不进 hydrate | 通过（新测） |
| 水印页 ACL 重验代码路径 | 已实现；专用「撤销后拒访」API 测待补 |
| Open API 对 confidential+ 强制截断导出 | 已实现；依赖既有 open_api 套件回归 |
| 流式中途 ACL 撤销 | 仍为已知窗口，未测 |

---

## 3. 是否建议进入生产试运行

**有条件建议**：单组织内网试运行可以，须先：

1. `alembic upgrade head`（含 `0021` lifecycle/classification）  
2. 重建或依赖 hydrate 过滤（无需强制全量 rebuild，但建议抽检过期文档）  
3. 确认备份异地与告警仍为待办（见 `docs/operations/backup-recovery.md`）

正式多工厂 / 强制审核制度库上线前，完成全量 pytest、vitest、备份演练与 P1 僵尸任务/告警闭环。
