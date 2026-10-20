# 文档生命周期

> 目标：在**不破坏现有入库状态与存量文档可见性**的前提下，补齐业务生命周期。  
> 入库状态 `DocumentStatus`（uploaded→…→indexed|failed）保持不变，表示处理管道。  
> 业务状态使用独立字段 `lifecycle_status`。

---

## 1. 状态

| 状态 | 含义 | 默认可检索作答 |
| --- | --- | --- |
| `draft` | 草稿，未提交审核 | 否 |
| `in_review` | 待审核 | 否 |
| `published` | 已发布；是否「生效」看 `effective_from`/`effective_to` | 窗口内：是 |
| `retired` | 已废止（人工） | 否 |
| `archived` | 已归档（只读保留） | 否 |

派生语义（不单独落库）：

- **已生效**：`lifecycle_status=published` 且当前时间 ∈ `[effective_from, effective_to)`（空表示不限）。  
- **已过期**：`published` 但已过 `effective_to`（hydrate 记 `not_in_effect`，可与 KO 对齐）。

存量迁移：现有文档 `lifecycle_status=published`，`effective_*` 原样保留 → **不导致全库不可见**。

---

## 2. 状态机

```text
        submit          approve
draft ────────► in_review ────────► published
  ▲                 │ reject              │
  └─────────────────┘                     ├── effective_to 到期 → 检索排除（仍 published）
                                          ├── retire → retired
                                          └── archive → archived

retired / archived ──(reopen, 需 manage)──► draft | published（按策略）
```

| 转换 | 所需权限 | 副作用 |
| --- | --- | --- |
| draft→in_review | EDIT | 审计；可选通知审核人 |
| in_review→published | MANAGE（或审核角色） | 审计；触发索引（若已 indexed）/缓存失效 |
| in_review→draft | EDIT | 审计 |
| published→retired | MANAGE | 审计；删索引或标记不可检；缓存失效 |
| *→archived | MANAGE | 同上 |
| 任意→改 effective_* | EDIT | 窗口变化影响检索；缓存失效 |

强制审核策略（SOP 等）：知识库或文档类型可配置 `require_review=true`（预留）；**不**把历史 `published` 自动降为草稿。

---

## 3. 对索引 / 缓存 / 历史版本

| 事件 | 索引 | 缓存 | 历史 |
| --- | --- | --- | --- |
| 进入不可检索状态 | Outbox 删除或 ACL/lifecycle 刷新后 hydrate 丢弃 | `invalidate_org` | 版本记录保留 |
| 恢复 published 且在窗内 | 重新 `DOCUMENT_CHUNKS_READY` 或 refresh | bump | — |
| 版本恢复 | 新版本 + 再解析索引；lifecycle 默认保持 | — | `restored_from` |

权威文本仍在 PG；索引可全量重建。

---

## 4. 与 KO / 复核的关系

- KO：已有 `draft→pending_review→published→deprecated` + `in_effect`。  
- 文档周期复核（`review_*`）继续作为**内容健康**提醒，不替代 lifecycle。  
- 过期提醒（`effective_to`）应与检索排除一致。

---

## 5. API（约定）

- `PATCH /documents/{id}`：可更新 `lifecycle_status`（受状态机约束）、`effective_*`、`classification`。  
- `POST /documents/{id}/lifecycle/{action}`：`submit` / `approve` / `reject` / `retire` / `archive` / `reopen`（实现阶段落地）。  
- 列表可按 `lifecycle_status` 筛选；默认列表对编辑者可见草稿，检索/问答仅生效文档。

---

## 6. 回滚

- Alembic：删列 `lifecycle_status` / `classification`；默认回填 `published`。  
- 应用回滚到旧镜像后，新列可忽略（若已写值不影响旧代码只选旧列）。
