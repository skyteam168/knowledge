# 企微 / 钉钉群机器人（问答入口 · 阶段 1）

群内发问 → 本平台用**开放平台应用身份**调用 `AnswerService` → 回带「答案 + 引用摘要」。

阶段 1 **不接**企微/钉钉消息加解密与真实云出站；用本地 token + mock JSON 冒烟即可。

---

## 1. 架构

```
群消息 / curl mock
  → POST /api/v1/integrations/{wecom|dingtalk}/bot
  → 校验 INTEGRATIONS_BOT_TOKEN
  → 用 INTEGRATIONS_BOT_OPEN_API_KEY 鉴权开放平台应用
  → OpenApiService.chat（非流式）
  → 纯文本 reply（答案截断 + [n] 引用标题）
```

权限与 ACL 与开放平台一致：授权库 ∩ 代理 principals；无超管旁路。

---

## 2. 管理端准备

1. 「管理 → 开放平台 → 新建应用」
   - 开通能力勾选 **问答（chat）**
   - 授权所需知识库 + 代理身份（部门/组/角色）
2. 创建 API Key，保存明文（仅显示一次）
3. 后端环境变量写入该 Key 与回调 token（见下节）

---

## 3. 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTEGRATIONS_BOT_ENABLED` | `false` | 总开关；关则接口 404 |
| `INTEGRATIONS_BOT_TOKEN` | 空 | 回调共享密钥（`X-Bot-Token` / `Authorization: Bearer` / `?token=`） |
| `INTEGRATIONS_BOT_OPEN_API_KEY` | 空 | 上述开放平台应用的 API Key |
| `INTEGRATIONS_BOT_MAX_ANSWER_CHARS` | `1200` | 群消息答案截断 |
| `INTEGRATIONS_BOT_MAX_CITATIONS` | `5` | 引用条数上限 |

`deploy/.env` 示例：

```env
INTEGRATIONS_BOT_ENABLED=true
INTEGRATIONS_BOT_TOKEN=dev-bot-token-change-me
INTEGRATIONS_BOT_OPEN_API_KEY=ekb_sk_xxxxxxxx
```

改完后重启 `backend`。

---

## 4. 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/integrations/wecom/bot?echostr=...&token=...` | URL 校验 stub：原样回 `echostr` |
| `POST` | `/api/v1/integrations/wecom/bot` | 企微/本地 mock 提问 |
| `POST` | `/api/v1/integrations/dingtalk/bot` | 钉钉/本地 mock 提问 |

请求头：`X-Bot-Token: <INTEGRATIONS_BOT_TOKEN>`（或 Bearer）。

### 4.1 本地 mock 体（推荐冒烟）

```json
{ "question": "织机保养周期是多久？" }
```

也兼容简化回调字段：

- 企微：`{"MsgType":"text","Content":"..."}`
- 钉钉：`{"text":{"content":"..."}}`

### 4.2 响应（JSON）

```json
{
  "reply": "……\n\n引用：\n[1] 织造手册",
  "conversation_id": "...",
  "message_id": "...",
  "grounding": "confident",
  "citation_count": 1,
  "trace_id": "...",
  "provider": "wecom"
}
```

真实群侧可将 `reply` 原样发回会话；阶段 1 不出站调用企微/钉钉 API。

---

## 5. 本地冒烟

前置：开放平台应用已建、Key 已写入 env、backend 已重启。

```bash
# WeCom URL echo
curl -sS "http://127.0.0.1:8000/api/v1/integrations/wecom/bot?echostr=ping&token=dev-bot-token-change-me"

# 提问（企微路由）
curl -sS -X POST "http://127.0.0.1:8000/api/v1/integrations/wecom/bot" \
  -H "Content-Type: application/json" \
  -H "X-Bot-Token: dev-bot-token-change-me" \
  -d "{\"question\":\"织机保养周期是多久？\"}"

# 提问（钉钉路由）
curl -sS -X POST "http://127.0.0.1:8000/api/v1/integrations/dingtalk/bot" \
  -H "Content-Type: application/json" \
  -H "X-Bot-Token: dev-bot-token-change-me" \
  -d "{\"text\":{\"content\":\"断纱怎么处理\"}}"
```

期望：HTTP 200，`reply` 非空；有召回时含 `引用：` 行。

单测（不启服务）：

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_integrations_bot.py -q
```

---

## 6. 后续（非本阶段）

- 企微 `msg_signature` 加解密、钉钉 `sign` 校验
- @机器人过滤、多轮会话映射 userid
- 主动出站 webhook / 卡片消息
- 按群绑定不同 Open API 应用
