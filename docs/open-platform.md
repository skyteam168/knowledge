# 开放平台使用说明书（外部 Agent 接入 / MCP）

开放平台让企业内外的 Agent、机器人、业务系统以 API Key 访问知识库，提供三种能力：

| 能力 | 接口 | 用途 |
| --- | --- | --- |
| 检索 `retrieve` | `POST /api/v1/open/retrieve` | 返回授权范围内最相关的原文片段及出处，调用方自己组织回答 |
| 问答 `chat` | `POST /api/v1/open/chat` | 直接返回带 `[n]` 引用的回答，支持多轮与 SSE 流式 |
| MCP `mcp` | `POST /api/v1/open/mcp` | 供支持 MCP 的 Agent（Cursor、Claude、各类 Agent 框架）以工具方式调用 |

---

## 1. 权限模型

外部 Agent 能看到的内容由两层共同决定，取交集：

1. **授权知识库（上限）**：管理员为应用勾选的知识库。未勾选的库无论如何都访问不到，请求时指定也会返回 `403 KB_NOT_GRANTED`。
2. **代理身份（文档级过滤）**：应用绑定的部门 / 用户组 / 角色。授权库里的文档仍按知识库和文档自身的 ACL 过滤，
   效果与「属于这些部门 / 组 / 角色的员工」完全一致。

补充规则：

- 绑定部门时自动包含其上级部门的授权（与员工一致：授权给「织造车间」，绑定「保全组长」的应用也能看到）。
- 每个应用对应一个服务账号 `agent:<client_id>`，只有 `search:use`（开通问答时加 `chat:use`）两个功能权限，
  永远不是超级管理员；绑定「知识库管理员」等角色也不会获得管理旁路。
- 「组织内所有人可读」的知识库，任何代理身份都能读到（只要该库在授权知识库中）。
- 检索时在 Qdrant / OpenSearch 前置过滤权限，返回前再用 PostgreSQL 二次校验；大模型只能看到通过校验的内容。

### 权限变更生效时间

| 操作 | 生效时间（实测） |
| --- | --- |
| 收回权限（改为受限、移除部门、调出部门、停用应用、吊销密钥） | 立即（0.02~0.03 s） |
| 授予部门 / 个人读权限 | 约 0.3 s |
| 改为「组织内所有人可读」 | 约 1.6~1.8 s（等待 worker 更新索引） |
| 修改应用的授权知识库、代理身份、能力 | 下一次请求立即生效 |

---

## 2. 管理员操作手册

### 2.1 前置条件

- 需要功能权限 `admin:openapi`（「管理开放平台（外部 Agent 接入）」）。平台管理员默认拥有；
  其他管理员需在「管理 → 角色权限」中给所在角色勾选该权限。
- 后端配置 `OPEN_API_ENABLED=true`（默认开启）。关闭后所有开放接口返回 `404 OPEN_API_DISABLED`。
- 生产环境必须设置 `OPEN_API_KEY_PEPPER`（见第 5 节）。

### 2.2 创建接入应用

入口：「管理 → 开放平台 → 新建应用」。

| 分组 | 字段 | 说明 |
| --- | --- | --- |
| 基本信息 | 应用名称、描述、归属部门、联系人 | 便于审计和追责，归属部门不影响权限 |
| 授权范围 | 授权知识库（必填，可多选） | 访问上限 |
| | 代理身份（必填，部门 / 用户组 / 角色至少选一个） | 决定授权库中哪些文档可读 |
| | 开通能力（必填） | 检索 / 问答 / MCP，可多选 |
| 安全与配额 | 每分钟限流 | 0 表示使用默认值（`OPEN_API_DEFAULT_RATE_PER_MINUTE`，默认 60） |
| | 每日配额 | 0 表示不限 |
| | IP 白名单 | 每行一个 IP 或 CIDR（如 `10.0.0.0/8`），留空表示不限 |
| | 有效期 | 到期后返回 `403 API_CLIENT_EXPIRED`，留空表示长期 |

建议：

- 一个外部系统一个应用，不要多个系统共用，便于单独停用和看日志。
- 代理身份按「这个 Agent 相当于哪个部门的员工」来选，不要为了方便绑定权限很大的角色。
- 先用「授权预览」确认能检索到的内容符合预期，再签发密钥给对方。

### 2.3 签发与管理密钥

入口：应用详情 →「密钥管理」。

- 点击「签发密钥」，可设置名称和过期时间。密钥形如 `ekb_sk_xxxxxxxx…`，**只在签发时显示一次**，
  系统只保存其 HMAC 哈希，丢失后无法找回，只能重新签发。
- 一个应用可以有多个有效密钥，用于无缝轮换：先签发新密钥 → 对方切换 → 吊销旧密钥。
- 「吊销」立即生效，之后使用该密钥返回 `401 API_KEY_REVOKED`。
- 列表显示密钥前缀、最近使用时间和 IP，用于识别是哪个密钥在调用。

### 2.4 应用详情页

| 标签页 | 内容 |
| --- | --- |
| 调用概览 | 近 7 / 14 / 30 天调用量、失败数、失败率、平均耗时，按接口分布 |
| 密钥管理 | 签发、吊销、查看使用情况 |
| 调用日志 | 每次调用的时间、接口、状态码、错误码、耗时、IP、查询内容（截断 500 字）、命中文档，可按状态筛选 |
| 授权预览 | 以该应用的身份做一次检索，结果与外部调用完全一致（预览本身记审计日志，不计入调用量） |
| 接入指南 | 当前环境的 curl 示例和 MCP 客户端配置，可直接复制给接入方 |

### 2.5 停用与删除

- **停用**：所有密钥立即失效（`403 API_CLIENT_DISABLED`），配置和日志保留，可随时重新启用。
- **删除**：应用、密钥一并删除，之后调用返回 `401`。调用日志和审计日志保留。

所有管理操作（创建、修改、签发、吊销、停用、删除、预览）都记录在「审计日志」中。

---

## 3. 接入方调用说明

### 3.1 认证

请求头二选一：

```http
X-API-Key: ekb_sk_xxxxxxxx
Authorization: Bearer ekb_sk_xxxxxxxx
```

基础地址：`https://<知识库域名>/api/v1/open`（开发环境 `http://localhost:3000/api/v1/open`）。

### 3.2 查看自身信息与可访问知识库

```bash
curl -H 'X-API-Key: <KEY>' https://kb.example.com/api/v1/open/whoami
```

```json
{
  "client_id": "8e03e7e4…",
  "name": "客服机器人",
  "scopes": ["chat", "retrieve"],
  "kbs": [{ "id": "185f23e3…", "name": "IT运维手册", "description": null }],
  "rate_limit_per_minute": 60,
  "daily_quota": 0
}
```

`kbs` 是「授权知识库」中当前代理身份确实能读的库。`GET /knowledge-bases` 只返回 `kbs` 列表。

### 3.3 检索 `POST /retrieve`（需开通「检索」）

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string，必填，≤1000 字 | 问题或关键词；支持 `"精确短语"`、`kb:库名` 等搜索语法 |
| `kb_ids` | string[]，可选 | 限定知识库，必须都在授权范围内；留空表示全部授权库 |
| `top_k` | int，默认 5 | 返回条数，服务端上限 `OPEN_API_MAX_TOP_K`（默认 20） |

```bash
curl -X POST https://kb.example.com/api/v1/open/retrieve \
  -H 'X-API-Key: <KEY>' -H 'Content-Type: application/json' \
  -d '{"query": "思科交换机 ACL 设置 vlan 访问控制", "top_k": 5}'
```

```json
{
  "query": "思科交换机 ACL 设置 vlan 访问控制",
  "kb_ids": ["185f23e3…"],
  "items": [
    {
      "rank": 1,
      "chunk_id": "…",
      "document_id": "…",
      "title": "思科交换机通过添加ACL设置不同vlan不同网段数据访问",
      "kb_id": "185f23e3…",
      "kb_name": "IT运维手册",
      "heading_path": ["配置步骤"],
      "content": "……",
      "score": 0.83,
      "page_start": null,
      "page_end": null,
      "is_ko": false
    }
  ],
  "total": 1,
  "trace_id": "…",
  "took_ms": 412.5
}
```

- `content` 每条最多 `OPEN_API_CONTENT_MAX_CHARS`（默认 2000）字；开启脱敏（`PII_MASK_ON_OUTPUT`）时手机号等会被打码。
- `score` 是 rerank 分数（0~1），可用来自行设定阈值。
- `is_ko=true` 表示命中的是审核发布的知识条目（KO）。

### 3.4 问答 `POST /chat`（需开通「问答」）

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `question` | string，必填，≤4000 字 | 问题 |
| `kb_ids` | string[]，可选 | 同检索 |
| `conversation_id` | string，可选 | 继续多轮对话，取上次返回的值；只能续接本应用自己的会话 |
| `stream` | bool，默认 false | true 时以 SSE 流式返回 |

**非流式**：

```bash
curl -X POST https://kb.example.com/api/v1/open/chat \
  -H 'X-API-Key: <KEY>' -H 'Content-Type: application/json' \
  -d '{"question": "如何远程查看服务器故障信息？"}'
```

```json
{
  "conversation_id": "…",
  "message_id": "…",
  "answer": "……[1]",
  "grounding": "grounded",
  "citations": [{ "n": 1, "document_id": "…", "chunk_id": "…", "title": "…", "kb_id": "…", "quote": "…" }],
  "steps": [{ "step": "rewrite", "status": "done", "ms": 1100, "detail": {} }],
  "trace_id": "…"
}
```

`grounding` 取值：

| 值 | 含义 | 建议处理 |
| --- | --- | --- |
| `grounded` | 有充分依据 | 直接使用 |
| `uncertain` | 依据一般，回答中会标出不确定部分 | 提示用户核实 |
| `low_grounding` | 生成了回答但没有有效引用 | 谨慎使用 |
| `no_evidence` | 知识库中没有可靠资料，已拒答（未调用大模型） | 转人工或提示补充资料 |
| `out_of_scope` / `chitchat` | 与知识库无关 / 闲聊 | 按业务处理 |

**流式**（`"stream": true`）返回 `text/event-stream`，事件依次为：

| 事件 | 数据 |
| --- | --- |
| `meta` | 会话 id、消息 id 等 |
| `step`（多次） | 处理步骤进度：`rewrite` 理解问题、`retrieve` 检索、`evidence` 筛选证据、`generate` 生成，含 `status`、`ms`、`detail` |
| `token`（多次） | 回答文本增量 |
| `citations` | 引用列表 |
| `done` | 完整回答、`grounding`、`trace_id` |
| `error` | 出错时代替 `done` |

```bash
curl -N -X POST https://kb.example.com/api/v1/open/chat \
  -H 'X-API-Key: <KEY>' -H 'Content-Type: application/json' \
  -d '{"question": "如何远程查看服务器故障信息？", "stream": true}'
```

### 3.5 错误码

错误响应统一为 `{code, message, detail, trace_id}`。

| HTTP | code | 含义 |
| --- | --- | --- |
| 401 | `INVALID_API_KEY` | 缺少密钥、格式错误或密钥不存在 |
| 401 | `API_KEY_REVOKED` / `API_KEY_EXPIRED` | 密钥已吊销 / 已过期 |
| 403 | `API_CLIENT_DISABLED` / `API_CLIENT_EXPIRED` | 应用已停用 / 已过期 |
| 403 | `IP_NOT_ALLOWED` | 来源 IP 不在白名单，`detail.ip` 为服务端看到的 IP |
| 403 | `SCOPE_DENIED` | 应用未开通该能力，`detail.required` 为所需能力 |
| 403 | `KB_NOT_GRANTED` | 请求了未授权的知识库，`detail.kb_ids` 列出被拒的库 |
| 404 | `OPEN_API_DISABLED` | 开放平台已关闭 |
| 404 | `NOT_FOUND` | `conversation_id` 不存在或不属于本应用 |
| 422 | `VALIDATION_ERROR` | 参数不合法 |
| 429 | `RATE_LIMITED` | 超过每分钟限流，响应头 `Retry-After` 为建议等待秒数 |
| 429 | `QUOTA_EXCEEDED` | 当日配额用完（UTC 日期切换后恢复） |

限流为 60 秒滑动窗口，按应用计（同一应用的多个密钥共享额度），所有接口（含 MCP）都计数。

---

## 4. MCP 协议接入

### 4.1 协议说明

- 传输：MCP Streamable HTTP，端点 `POST /api/v1/open/mcp`，响应为 JSON（不使用服务端推送，`GET` 返回 405）。
- 协议版本：`2025-06-18`、`2025-03-26`、`2024-11-05`；客户端请求其他版本时按 `2025-06-18` 协商。
- 需要应用开通「MCP」能力；工具列表随应用开通的其他能力变化：

| 工具 | 需要的能力 | 参数 | 返回 |
| --- | --- | --- | --- |
| `list_knowledge_bases` | 仅 MCP | 无 | `{knowledge_bases: [{id, name, description}]}` |
| `search_knowledge` | MCP + 检索 | `query`（必填）、`kb_ids`、`top_k`（1~20，默认 5） | 同 `/retrieve` 响应 |
| `ask_knowledge` | MCP + 问答 | `question`（必填）、`kb_ids`、`conversation_id` | 同 `/chat` 非流式响应 |

- 支持的方法：`initialize`、`notifications/*`、`ping`、`tools/list`、`tools/call`，支持 JSON-RPC 批量请求。
- 工具结果同时提供 `content`（JSON 文本，给模型阅读）和 `structuredContent`（结构化数据）。
- 业务错误（如 `KB_NOT_GRANTED`、限流）以 `isError: true` 的工具结果返回，模型能看到原因；
  协议错误以 JSON-RPC 错误返回：

| code | 含义 |
| --- | --- |
| -32700 | 请求体不是合法 JSON（HTTP 400） |
| -32600 | 不是合法的 JSON-RPC 2.0 消息或空批量 |
| -32601 | 方法不存在 |
| -32602 | 参数错误（未知工具、`params` / `arguments` 不是对象） |
| -32603 | 服务端内部错误 |

密钥、应用状态、IP、限流的校验发生在 MCP 处理之前，失败时返回第 3.5 节的 HTTP 错误。

### 4.2 客户端配置

**Cursor**（`~/.cursor/mcp.json` 或项目 `.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "enterprise-kb": {
      "url": "https://kb.example.com/api/v1/open/mcp",
      "headers": { "X-API-Key": "<YOUR_API_KEY>" }
    }
  }
}
```

**只支持 stdio 的客户端**（如 Claude Desktop），用 `mcp-remote` 桥接：

```json
{
  "mcpServers": {
    "enterprise-kb": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://kb.example.com/api/v1/open/mcp",
        "--header", "X-API-Key:${EKB_API_KEY}"
      ],
      "env": { "EKB_API_KEY": "<YOUR_API_KEY>" }
    }
  }
}
```

**自研 Agent**：任何 MCP SDK 的 Streamable HTTP 客户端都可以直接连接，在请求头中带上 `X-API-Key`。

### 4.3 用 curl 自测

```bash
URL=https://kb.example.com/api/v1/open/mcp
H='X-API-Key: <KEY>'

curl -s -X POST $URL -H "$H" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

curl -s -X POST $URL -H "$H" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

curl -s -X POST $URL -H "$H" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_knowledge","arguments":{"query":"ESXI 创建虚拟机","top_k":3}}}'
```

---

## 5. 运维与安全配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `OPEN_API_ENABLED` | `true` | 总开关 |
| `OPEN_API_KEY_PEPPER` | `change-me-open-api-pepper` | 密钥哈希的 HMAC 密钥。生产必须设置为随机长字符串（`docker-compose.prod.yml` 未设置会拒绝启动）；**修改后所有已签发密钥失效**，需要全部重新签发 |
| `OPEN_API_DEFAULT_RATE_PER_MINUTE` | `60` | 应用限流填 0 时使用 |
| `OPEN_API_MAX_TOP_K` | `20` | 检索返回条数上限 |
| `OPEN_API_CONTENT_MAX_CHARS` | `2000` | 每条片段返回的最大字数 |
| `OPEN_API_LOG_QUERY_CHARS` | `500` | 调用日志记录的查询字数 |
| `OPEN_API_TRUSTED_PROXIES` | `[]` | 可信代理的 IP / CIDR（JSON 数组），只有来自这些地址的 `X-Forwarded-For` 才被采信 |

IP 白名单相关的部署要求：

- 后端只通过前端 nginx 对外暴露，**不要把后端 8000 端口直接暴露到外网**。
- `frontend/nginx.conf` 用 `proxy_set_header X-Forwarded-For $remote_addr` 覆盖（而不是追加）该头；
  如果前面还有负载均衡，把负载均衡的地址加入 `OPEN_API_TRUSTED_PROXIES`，并确认它同样覆盖该头。
- 自查方法：配置一个只允许内网网段的白名单，从外网调用应返回 `403 IP_NOT_ALLOWED`，且 `detail.ip` 是真实来源 IP。

限流和配额计数存放在 Redis，Redis 不可用时放行（记录 `open_api_limit_unavailable` 警告日志），不影响业务可用性。

数据与日志：

| 数据 | 位置 |
| --- | --- |
| 应用、密钥哈希 | PostgreSQL `api_clients`、`api_keys` |
| 调用日志 | PostgreSQL `api_call_logs`（请求结束后独立事务写入，业务失败也会记录） |
| 审计 | 审计日志 `openapi.*` 动作（检索、问答建会话、管理操作） |
| 检索链路 | 「检索 trace」，可用调用日志中的 `trace_id` 关联 |

常见问题排查：

| 现象 | 排查 |
| --- | --- |
| 总是 401 `INVALID_API_KEY` | 密钥是否完整复制（以 `ekb_sk_` 开头）；是否修改过 `OPEN_API_KEY_PEPPER` |
| 403 `IP_NOT_ALLOWED` 但 IP 确实在白名单 | 看 `detail.ip`：如果是代理地址，按上文配置 nginx / `OPEN_API_TRUSTED_PROXIES` |
| `whoami` 的 `kbs` 为空或缺少某个库 | 代理身份在该库中没有读权限：给该部门 / 组 / 角色授权，或把库设为「组织内所有人可读」 |
| 检索结果为空 | 用「授权预览」以同样身份检索对比；确认文档已索引完成 |
| MCP 客户端看不到某个工具 | 应用需同时开通 MCP 和对应能力（检索 / 问答） |

---

## 6. MCP 的维护与扩展（开发者）

### 6.1 代码位置

| 文件 | 职责 |
| --- | --- |
| `backend/app/api/v1/open_api.py` | 开放接口路由、API Key 认证依赖、调用日志写入、`/mcp` 端点 |
| `backend/app/services/open_api/mcp.py` | MCP 协议处理：版本协商、方法分发、工具定义 `TOOLS`、能力映射 `TOOL_SCOPES`、工具执行 |
| `backend/app/services/open_api/open_service.py` | 检索 / 问答业务（REST 和 MCP 共用），授权库上限在这里执行 |
| `backend/app/services/open_api/auth.py` | 密钥校验、应用状态、IP 白名单、限流配额、代理身份构建 |
| `backend/app/services/open_api/client_service.py` | 应用与密钥管理 |
| `backend/app/api/v1/open_admin.py` | 管理接口（`/admin/open-api/*`，需 `admin:openapi`） |
| `backend/app/models/open_api.py`、`backend/app/schemas/open_api.py` | 数据模型与接口 schema |
| `frontend/src/views/admin/openApi/` | 管理页面；`meta.ts` 定义能力说明 |
| `backend/tests/test_open_api.py` | 开放平台测试（认证、越权、限流、MCP 协议等） |

### 6.2 新增一个 MCP 工具

以新增「按文档 id 取全文」工具 `get_document` 为例：

1. **定义工具**：在 `mcp.py` 的 `TOOLS` 中增加一项，写清 `name`、`title`、`description`（模型靠它决定何时调用）、
   `inputSchema`（JSON Schema，设置 `additionalProperties: false`），只读工具加 `annotations.readOnlyHint: true`。
2. **绑定能力**：在 `TOOL_SCOPES` 中声明需要的能力，例如 `"get_document": ApiScope.RETRIEVE`。不声明则只要开通 MCP 就可见。
3. **实现业务**：在 `OpenApiService` 中新增方法，必须遵守：
   - 用 `self.caller.resolve_kbs()` 或检查 `self.caller.kb_ids` 限定授权库上限；
   - 文档访问通过 `KnowledgeAccess` / 现有服务以 `self.ctx.user`（代理身份）校验读权限，**不要直接查表绕过 ACL**；
   - 返回给外部的正文按 `OPEN_API_CONTENT_MAX_CHARS` 截断，开启脱敏时调用 `PiiMasker`；
   - 记录审计日志（参考 `retrieve` 中的 `openapi.retrieve`）。
4. **接入分发**：在 `McpServer._run_tool` 中增加分支，入参用 pydantic schema 校验
   （`ValidationError` 会自动转成 `isError` 的工具结果），并调用 `self.on_tool(name, {...})` 写调用日志
   （日志里的接口名为 `mcp:get_document`）。
5. **（可选）REST 接口**：如需同时提供 REST，在 `open_api.py` 增加路由，使用 `_Call` 记录日志、`caller.require_scope()` 校验能力。
6. **测试**：在 `test_open_api.py` 中至少覆盖：
   - 未开通对应能力时工具不在 `tools/list` 中、`tools/call` 返回 -32602；
   - 未授权知识库 / 代理身份无权的文档访问不到；
   - 参数错误返回 `isError: true`；
   - 调用日志中有对应记录。
7. **更新文档**：本文第 4.1 节工具表。

### 6.3 新增一种能力（scope）

1. 在 `backend/app/models/open_api.py` 的 `ApiScope` 中增加枚举值（`scopes` 字段是 JSON 数组，不需要数据库迁移）。
2. 如果新能力需要额外的功能权限，在 `auth.py` 的 `caller_user()` 中按能力追加，**只追加最小必要权限**。
3. 前端 `frontend/src/api/types.ts` 的 `ApiScope` 类型和 `views/admin/openApi/meta.ts` 的 `SCOPE_INFO` 中补充名称和说明，
   管理页面的能力勾选会自动出现。
4. 补充测试并更新本文档。

### 6.4 协议版本升级

- MCP 发布新协议版本时，确认变更点（方法、字段、传输）后在 `SUPPORTED_VERSIONS` 头部加入新版本；
  第一个元素是默认协商版本。旧版本保留至主流客户端都已升级。
- 如果需要服务端推送（如工具列表变化通知），需要实现 `GET /mcp` 的 SSE 流并把
  `capabilities.tools.listChanged` 改为 `true`；当前实现不推送，`GET` 返回 405 符合规范。
- 修改 `SERVER_INFO.version` 便于客户端识别。

### 6.5 修改后的验证

```bash
cd backend
uv run pytest tests/test_open_api.py -q      # 开放平台测试
uv run pytest -q                             # 全量
uv run ruff check app tests && uv run mypy app
```

部署：`docker compose -f deploy/docker-compose.yml up -d --build backend`，再用第 4.3 节的 curl 命令或 MCP 客户端实测。

### 6.6 安全检查清单

新增或修改开放接口 / 工具前逐项确认：

- [ ] 结果只来自 `caller.kb_ids` 内的知识库
- [ ] 文档级权限按代理身份校验，没有绕过 ACL 的查询
- [ ] 不返回内部字段（存储路径、其他用户信息、原始 prompt）
- [ ] 输出长度有上限，脱敏配置生效
- [ ] 能力校验（`require_scope` / `TOOL_SCOPES`）到位
- [ ] 写了调用日志和审计日志
- [ ] 有越权、参数错误的测试
