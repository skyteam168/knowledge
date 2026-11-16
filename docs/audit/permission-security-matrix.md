# 权限与安全矩阵

> 基于源码：`services/authz/*`、`services/knowledge/access.py`、`retrieval/filters.py`、`services/open_api/auth.py`。  
> 冲突规则：allow-list + 显式 DENY（`resource_acl.effect`）；多条 allow 取最高权限（`read < edit < manage`）；**DENY 优先于 allow 与 org 可见**（超管除外；KB manage 可越过文档 DENY 以修复 ACL）。详见 [`docs/adr/0002-explicit-acl-deny.md`](../adr/0002-explicit-acl-deny.md)。

---

## 1. 主体与租户

| 主体类型 | 来源 | 说明 |
| --- | --- | --- |
| `user` | 登录用户 | 始终包含 |
| `org` | 组织 | 用于 `visibility=org` 的 KB 全员可读 |
| `group` / `role` / `dept` | 成员关系 | dept 含祖先 ID（上级授权对下级生效） |

查询默认带 `org_id`；跨 org 资源以 404 呈现（不泄露存在性）。`is_superuser`（权限含 `*`）绕过资源 ACL，**不**绕过 Open API 服务账号边界。

---

## 2. 功能权限（RBAC）与资源 ACL

| 操作 | RBAC（路由级） | 资源 ACL（服务级） |
| --- | --- | --- |
| 搜索 | `search:use` | 索引 `AclFilter` + hydrate |
| 问答 | `chat:use` | 检索 ACL + `EvidenceAclChecker` |
| 读文档 / 预览 / 版本 | `kb:read` 等 | `require_document(READ)` |
| 下载原文件 | 同上 | READ + `protection.can_download` |
| 编辑 / 新版本 / 恢复 | `kb:write` 或等价 | `require_document(EDIT)` |
| 改 ACL | 路由可能仅 `kb:read` | **必须** `MANAGE`（服务内强制） |
| 删文档 | `doc:delete` | + `EDIT` |
| 管理助手写工具 | `AGENT_ACCESS` 入口 | 每工具再检具体 admin 权限 |

前端 `v-permission` / 菜单隐藏 **不是** 安全边界。

---

## 3. 知识库 / 文档继承

| 规则 | 行为 |
| --- | --- |
| KB `visibility=org` | 组织成员默认 READ，更高权限靠 ACL |
| KB `visibility=restricted` | 仅 ACL 主体 |
| `document.acl_inherit=true` | 用 KB ACL；KB MANAGE 始终可管文档 |
| `acl_inherit=false` | 用文档自身 ACL |
| 文档保护 | 相对 KB 只能加严（水印 / 禁复制 / 下载门槛） |

---

## 4. 历史版本 / 引用 / 缓存 / 流式

| 场景 | 策略 |
| --- | --- |
| 历史版本查看 | 对**当前文档**做 READ；版本行不另开旁路 |
| 版本恢复 | 需 EDIT；产生新版本 |
| 引用打开 | 消息归属校验 + **当前**文档 READ |
| 检索缓存 | key 含 org + principals_hash + generation；命中后仍 hydrate |
| ACL 变更 | Outbox → 刷索引 principals → `invalidate_org` |
| 流式问答 | 生成前 + 流式每 N 字 + 生成后 Evidence ACL；中途撤权中止续写并以拒答落库。**残余窗口**：撤权检测前已推送给客户端的 token 无法收回 |
| 水印页签名 URL | 签发时有权；访问时应重验文档 READ（见修复） |

---

## 5. Open API / MCP / Worker / 管理助手

| 身份 | 边界 |
| --- | --- |
| API Key | active/revoked/expired；client 禁用/过期；IP 白名单；分钟限流；日配额 |
| 服务账号 | 绑定 principals × `allowed_kb_ids`；permissions 仅 search/chat；`is_platform_admin=False` |
| MCP 工具 | 按 scope 暴露；业务走同一 OpenApiService |
| Worker | 系统维护派生索引；无终端用户超管旁路 |
| Admin Agent | 工具权限 + risk/approval；执行走原 admin service |

Key 轮换：新建 key + 吊销旧 key（无独立 rotate API）。

---

## 6. 撤销生效

| 变更 | 生效路径 |
| --- | --- |
| 文档/KB ACL | 索引刷新 + ResultCache generation++；hydrate 即时丢无权 |
| 组/角色成员 | AuthzCache invalidate；新请求 principals_hash 变化 |
| API Key 吊销 | 下次请求认证失败 |
| 已签发预签名 / 水印链 | TTL 内曾可访问 → **须访问时重验 ACL** |

---

## 7. 已知缺口（跟踪）

1. ABAC 密级已部分落地（B1）；显式 DENY 已落地（B3 / ADR 0002）。  
2. 流式生成中 ACL 重绑（P1）。  
3. MinIO 预签名 GET 在对象层不重验 ACL（缩短 TTL + 水印页已覆盖敏感预览）。
