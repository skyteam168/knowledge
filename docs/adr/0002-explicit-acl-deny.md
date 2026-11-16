# ADR 0002：显式 ACL DENY

- 状态：已采纳（2026-11-14）
- 关联：TASK B8 之后的 B3

## 背景

`resource_acl` 原为纯 allow-list：同一主体多条 grant 取最高权限（read < edit < manage）；`visibility=org` 等价组织级隐式 READ。无法在「组织可见」知识库中单独剔除某用户。

## 决策

1. `resource_acl.effect`：`allow`（默认）| `deny`。
2. **Deny-wins**：匹配主体的 DENY 优先于一切 allow grant 与 org 可见；超管除外。
3. **文档 / KO 级 DENY 在 `acl_inherit=true` 时仍生效**，用于组织可见库剔除个人。
4. **KB `manage` 豁免文档 DENY**：管理员仍可读文档以修复 ACL；KB 自身 DENY 仍对非超管生效。
5. 阶段 1 索引可不写 `acl_deny_principals`：检索预过滤可能多召回，**hydrate / EvidenceAclChecker 以 PG 复核为准**。

## 后果

- API/UI：`AclEntry.effect`；文档继承模式下可维护拒绝名单。
- 变更仍走 `ACL_CHANGED` outbox → 缓存失效。
- 后续可选：索引 `must_not` DENY 主体，降低无效召回。
