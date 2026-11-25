# 业务语义中心（运维入口）

组织侧「业务语义」四块能力与管理入口：

| 能力 | 管理入口 | API 前缀 | Agent 可见性 |
|------|----------|----------|--------------|
| 字段/对象/关系/版本 | Ontology Studio | `/admin/ontology` | 仅 **published**（`describe_ontology`） |
| 语义证据（KO/文档/chunk） | Studio 证据面板 | `/admin/ontology/.../evidences` | published 摘要（无正文） |
| 跨系统 ID | 跨系统身份 | `/admin/structured/identity` | `get_object.identifiers` |
| 业务规则 + Action | 规则与动作 | `/admin/ontology/rules`、`/action-types` | Runtime / `list_actions`（禁用不可见） |
| 计算口径 | 属性 `compute_expr` | Studio 属性表单 | `get_object.derived` |

## 约束

- 密码/密钥走环境变量；写操作记审计。
- 计算表达式仅允许数字四则与属性名（AST 沙箱），禁止任意代码。
- 证据读路径经 KO/文档 ACL；不可见目标不会泄露正文。
- 身份冲突走 `resolve_match`，不可静默覆盖。

## 验收清单

1. 草稿挂证据 → 发布 → MCP `describe_ontology` 含 evidences；草稿版本 MCP 不可见。
2. 身份台可建 Canonical、挂 Identifier、看 conflicts。
3. 规则禁用 / Action 禁用后 list_actions 行为符合预期。
4. `compute_expr="a+b"` 在 attrs 上派生；非法 token 被拒绝。
