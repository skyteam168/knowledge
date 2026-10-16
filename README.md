# 企业知识库平台（Enterprise Knowledge Base）

当前阶段：**阶段 7 — 分析与加固**（已完成）。已具备文档入库与索引、权限过滤的混合检索与重排、带引用的流式问答，
以及运营分析看板、离线评测、可观测性、安全加固、压测与生产部署；已接入阿里云百炼真实模型（见下文）。
近期补充：页/幻灯片附图入库、答案内嵌图与可视化、Open API / MCP 返回 `image_url`（见「文档附图与答案可视化」）。

| 阶段 | 名称 | 主要内容 |
| --- | --- | --- |
| 0 | 工程骨架 | 前后端脚手架、docker compose 基础设施（PG、Redis、MinIO、Qdrant、OpenSearch+IK、Keycloak、mock 模型） |
| 1 | 身份与权限 | Keycloak OIDC 登录与 JWT 校验、组织/部门/用户/组/角色、RBAC 功能权限、资源级 ACL、审计日志 |
| 2 | 知识库与文档入库 | 知识库与文档管理、MinIO 上传与 sha256 去重、多格式解析、父子块语义切分、Outbox 事件 |
| 3 | 索引层 | 模型网关（Embedding / Rerank / Chat）、Outbox 分发与死信、Qdrant / OpenSearch 同步、别名蓝绿重建 |
| 4 | 检索引擎 | 向量 + BM25 双路召回、ACL 前置过滤、RRF 融合、Rerank、检索 trace、权限隔离缓存、搜索页面 |
| 5 | AI 助手问答 | 多轮会话、问题改写与意图分类、知识扩展、ACL 复检、证据阈值校验、带引用的流式回答 |
| 6 | 知识闭环 | 知识缺口收集与聚类、审核工作台、LLM 辅助生成知识条目（KO）、发布审核与重新索引 |
| 7 | 分析与加固 | 运营分析看板、离线评测、OpenTelemetry / Prometheus、限流与脱敏、压测、生产部署 |

## 目录

```
backend/    FastAPI 后端 + Dramatiq worker（uv 管理依赖）
frontend/   Vue 3 + TS + Vite + Element Plus 前端
deploy/     docker-compose 及各基础设施配置（opensearch IK、keycloak realm、mock-llm）
docs/       ADR 与接口说明
```

## 一键启动（全部容器）

```bash
cp deploy/.env.example deploy/.env   # 可选，默认值即可运行
make up                              # = docker compose -f deploy/docker-compose.yml up -d --build --wait
```

| 服务 | 地址 | 账号 |
| --- | --- | --- |
| 前端 | http://localhost:3000 | - |
| 后端 API / 文档 | http://localhost:8000/docs | - |
| 就绪检查 | http://localhost:8000/ready | - |
| Keycloak | http://localhost:8080 | admin / admin |
| MinIO 控制台 | http://localhost:9001 | minioadmin / minioadmin |
| OpenSearch | http://localhost:9200 | 安全插件已关闭（仅开发） |
| Qdrant | http://localhost:6333/dashboard | - |
| Mock 模型服务 | http://localhost:9100/docs | - |

OpenSearch Dashboards 为可选服务：`docker compose -f deploy/docker-compose.yml --profile dashboards up -d`。

Keycloak 预置 realm `ekb`：客户端 `ekb-frontend`（public + PKCE）、`ekb-backend`（audience）；
测试用户 `alice`(kb_admin) / `bob`(kb_editor) / `carol`(kb_viewer)，密码均为 `password`，
组 `engineering`、`sales`，用户属性 `org_id=org-demo`（映射到 token claim `org_id`、`groups`）。

## 本地开发

依赖：Docker、Python 3.11 + [uv](https://docs.astral.sh/uv/)、Node 22。

```bash
make install       # 安装后端/前端依赖
make dev           # 启动基础设施容器 + 迁移 + 后端(8000)/worker/前端(5173) 热重载
make migrate       # alembic upgrade head
make test          # pytest + vitest
make lint          # ruff + mypy + eslint + prettier + vue-tsc
make down
```

Windows 无 `make` 时可直接执行 Makefile 中对应命令。后端本地配置见 `backend/.env.example`。

模型服务默认指向内置 mock（OpenAI 兼容 `/v1/embeddings`、`/v1/rerank`、`/v1/chat/completions`），
接入真实 vLLM / TEI 时修改 `EMBEDDING_BASE_URL`、`RERANK_BASE_URL`、`CHAT_BASE_URL` 及模型名即可。

## 接入真实模型（阿里云百炼 / DashScope）

所有模型配置都在 `deploy/.env`（开发）或 `deploy/.env.prod`（生产，模板见 `deploy/.env.prod.example`），
修改后执行 `docker compose -f deploy/docker-compose.yml up -d backend worker outbox-dispatcher scheduler` 生效。

| 用途 | 模型 | 接口 |
| --- | --- | --- |
| Embedding | `text-embedding-v4`（1024 维；也可用 `text-embedding-v3`、`qwen3.7-text-embedding`） | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/embeddings` |
| Rerank | `qwen3-rerank` | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-api/v1/reranks` |
| Chat / 评测裁判 | `deepseek-v4-flash`（可换成 `/models` 列表中的任意对话模型） | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions` |

```dotenv
EMBEDDING_BASE_URL=https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_SEND_DIMENSIONS=true
EMBEDDING_BATCH_SIZE=10            # v3/v4 单次最多 10 条，qwen3.7-text-embedding 最多 20 条
RERANK_BASE_URL=https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-api/v1
RERANK_MODEL=qwen3-rerank
RERANK_PATH=/reranks               # 自建 vLLM / TEI 为 /rerank
CHAT_BASE_URL=https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=deepseek-v4-flash
CHAT_EXTRA_BODY={"enable_thinking": false}   # 关闭思考模式，首 token 约 0.4s
CHAT_EVIDENCE_MIN_SCORE=0.45       # 见下方「离线评测基线」
CHAT_EVIDENCE_CONFIDENT_SCORE=0.7
CHAT_ANSWER_IMAGES_ENABLED=true    # 答案材料挂页图 URL，模型可 Markdown 内嵌
CHAT_ANSWER_IMAGES_PER_MATERIAL=2
CHAT_ANSWER_IMAGES_TOTAL=6
# PAGE_IMAGE_ENABLED=true          # 入库时生成 PDF/PPT/图片页光栅（默认开）
# PDF_PARSER=auto                  # auto|docling|mineru|basic；mineru 需 MINERU_API_URL
LLM_API_KEY=<百炼 API Key>
MOCK_EMBEDDING_DIM=1024
```

注意事项：

- Rerank 走 `compatible-api/v1`，用 `compatible-mode/v1/reranks` 会返回 404。
- 新增配置项：`RERANK_PATH`、`RERANK_INSTRUCT`（可选的 rerank 指令）、`CHAT_EXTRA_BODY`（合并进 chat 请求体，
  不能覆盖 `model` / `stream`）、`CHAT_EVIDENCE_MIN_SCORE`、`CHAT_EVIDENCE_CONFIDENT_SCORE`、
  `CHAT_ANSWER_IMAGES_*`，`deploy/docker-compose.yml` 已透传。
- 更换 Embedding 模型或维度后需要重建索引（新索引代次会记录自己的 embedding 配置，重建成功后才切换）：
  `docker compose -f deploy/docker-compose.yml exec backend python -m app.cli index rebuild --embedding-model text-embedding-v4 --embedding-dim 1024 --strict`
- 想切回内置 mock：三个 `*_BASE_URL` 改为 `http://mock-llm:9100/v1`，模型改为 `mock-embedding` / `mock-reranker` / `mock-chat`，
  `RERANK_PATH=/rerank`，`CHAT_EXTRA_BODY={}`。
- 宿主机 6379 端口被占用时，设置 `REDIS_HOST_PORT`（如 `6380`），容器间通信不受影响。
- `deploy/.env` 含 API Key，不要提交到仓库。
- 仓库已加 `.gitattributes`（`*.sh` 强制 LF），后端镜像构建时也会去掉 `docker-entrypoint.sh` 的 CRLF，
  避免在 Windows 上检出后容器启动报 “No such file”。

## 离线评测基线（2026-10-09）

模型组合：`text-embedding-v4`（1024 维）+ `qwen3-rerank` + `deepseek-v4-flash`（同时作为裁判模型），
索引代次 v4（23 篇文档 / 174 个 chunk），检索策略 `builtin`，开启大模型评分。

评测集「真实模型基线」共 32 题：

- 可回答 24 题：覆盖 IT 运维（ESXI、机房巡检、锁屏、离职权限）、网络安全培训（仿冒邮件、防火墙、WannaCry、杀毒）、
  邮件错误码、思科 ACL、邮箱诊断地址、视频会议 IP、差旅制度、飞织工艺、季度经营回顾、设备考核，每题标注期望文档和参考答案。
- 知识库外 8 题：年假、加班费、VPN 申请、发薪日、打印机卡纸、食堂、五险一金、出国住宿标准，期望拒答。

检索与回答质量（两次运行一致）：

| 指标 | 结果 |
| --- | --- |
| Recall@5 / Recall@10 | 1.0 / 1.0 |
| MRR / nDCG@10 | 1.0 / 1.0（24 题的期望文档都排第 1） |
| 忠实度 / 切题度 / 引用正确率（裁判打分） | 1.0 / 1.0 / 1.0 |
| 引用精确率 | 0.97 |
| 单题平均耗时 | 约 3.2 s |
| 降级 / 错误 | 0 / 0 |

rerank 最高分分布：

| 类别 | rerank 最高分 |
| --- | --- |
| 可回答 | 最低 0.551，其余都在 0.795 以上（多数大于 0.86） |
| 知识库外 | 0.301 ~ 0.417（「出国住宿标准」除外，因差旅制度文档高度相关，得分 0.802） |

拒答阈值调整（rerank 最高分低于 `CHAT_EVIDENCE_MIN_SCORE` 直接拒答，介于两个阈值之间回答但标记「不确定」）：

| | 默认 0.2 / 0.5 | 调整后 0.45 / 0.7 |
| --- | --- | --- |
| 可回答 24 题 | 24 题正常回答 | 23 题正常回答，1 题「不确定」（远程查看服务器故障信息，0.551） |
| 知识库外 8 题 | 0 题拒答（6 题低可信、1 题不确定、1 题正常回答） | 7 题直接拒答，1 题正常回答 |

- 默认阈值下知识库外问题全部交给大模型，大模型虽然回答了“无法确定”，但多一次模型调用，且被记为低可信而不是拒答。
- 「出国住宿标准」漏过阈值，但大模型正确回答“资料只有国内标准，无法确定出国标准”，属于预期行为。
- 0.45 距知识库外最高分 0.417 只有约 0.03 的余量。文档增多后应继续扩充评测集复跑：出现可回答题被误拒就下调到 0.4，
  出现知识库外问题漏过就上调到 0.5。
- 阈值只适用于 `qwen3-rerank`，换 rerank 模型后需要重新校准。

两次运行（「真实模型基线（默认阈值 0.2/0.5）」和「真实模型基线（阈值 0.45/0.7）」）都可以在前端「离线评测」页面的对比视图中查看逐题差异。

## 文档附图与答案可视化

入库与解析：

- 常见 PDF / PPT(X) / Word；**`.doc`** 经 LibreOffice（容器内需 `soffice`）转 docx 再解析；**`jpg` / `png`** 经 RapidOCR 抽取文字。
- 解析时可生成页或幻灯片光栅图，落入 `document_page_assets` 与 MinIO（配置 `PAGE_IMAGE_*`）。页图不进向量索引，供预览与配图。
- PDF 后端：`PDF_PARSER=auto|docling|mineru|basic`；选 `mineru` 时需部署 MinerU 服务并配置 `MINERU_API_URL`。

助手回答：

- Markdown 表格、`echarts` / `mermaid` 代码块；仅允许 `https` 或同源 `/api` 图片地址。
- **一期**：引用悬停与原文抽屉按需加载页图签名 URL。
- **二期**：证据材料中附带签名图 URL，模型可用 `![说明](url)` 内嵌；落库前剥离未在材料中出现的图片链接。
  开关与配额见上文 `CHAT_ANSWER_IMAGES_*`。

开放平台 / MCP：

- `search_knowledge` / `POST /open/retrieve`：命中条目含 `image_url`、`image_mime_type`（无页图则为 `null`）。
- `ask_knowledge` / chat：`citations[]` 含 `image_url`；`answer` 中也可能含 Markdown 图片。签名链接会过期。
- MCP 问答与站内助手共用同一 `AnswerService`；检索共用 `SearchService`。身份、授权知识库、`top_k`、会话历史不同时，结果不必与助手逐字相同。

## 开放平台（外部 Agent 接入）

管理员在「管理 → 开放平台」创建接入应用并签发 API Key，外部 Agent 通过 REST（检索 / 问答）或 MCP 协议访问知识库。
授权由两层共同决定：应用被授权的知识库是上限，应用绑定的代理身份（部门 / 用户组 / 角色）决定其中哪些文档可读，
和同身份员工看到的内容一致。使用说明、接口、MCP 接入与维护见 [docs/open-platform.md](docs/open-platform.md)。
检索 / 问答返回字段中的附图见上一节。

## 组织架构同步与扫码登录

「管理 → 组织同步」可从企业微信、钉钉、泛微 e-cology 9（只读库直连，SQL Server / Oracle / MySQL）或 Excel 同步部门、人员、
多部门归属与职务，每个组织选一个主数据源；支持企业微信 / 钉钉扫码登录（后端 OIDC 桥接 + Keycloak 身份代理），
账号密码作为兜底。部门在授权选择框中显示完整路径。准备工作、配置与排障见 [docs/ops/directory-sync.md](docs/ops/directory-sync.md)。

### 测试结果（2026-10-09）

> 没有企业微信、钉钉、泛微的真实凭据，**以下结果全部基于模拟上游**，真实环境连通性需要提供测试凭据后联调。

自动化测试：后端 pytest 292 项通过（本次新增 49 项：对账引擎 10、连接器 13、组织同步接口 5、扫码登录桥接 21），
ruff、mypy 无问题；前端 vitest 51 项通过，vue-tsc、eslint、prettier 无问题。

| 类别 | 覆盖内容 |
| --- | --- |
| 连接器（模拟接口） | 企业微信 token 过期重试、错误码提示；钉钉递归部门、游标分页、token 刷新；泛微在 SQLite 中建 e-cology 9 表结构子集，覆盖分部嵌套、封存、次账号兼职、在职状态、自定义 SQL 与只读校验；Excel 模板往返与校验 |
| 对账引擎 | 新增、改名、移动、归档、多部门、职务组、停用保护、主数据源只读、多数据源身份匹配 |
| 扫码登录桥接 | 完整 authorize → 回调 → token 流程并用 JWKS 校验 id_token；state 篡改、跨浏览器、伪造 cookie、授权码重放、redirect_uri / client_secret 错误、未同步 / 已停用 / 非本企业成员、企业微信内免扫码、钉钉 unionid 映射、生产缺签名密钥拒绝 |

现场验证：运行中的全套容器 + 真实 Keycloak，只有企业微信接口用模拟服务代替（3000 人、125 个部门），测试数据已清理。

| 场景 | 实测结果 |
| --- | --- |
| 测试连接 | 125 个部门、3000 人，1095 ms |
| 首次预览 | 新增 125 部门 / 3000 人，服务端 1131 ms；预览不写库 |
| 首次应用 | 服务端 1967 ms（含请求 3.05 s） |
| 无变化再同步 | 3000 人无变化，1246 ms |
| 变更预览 / 应用 | 新增 20 人、停用 30 人、部门移动 1 个 / 改名 2 个，1167 ms / 1188 ms |
| 完整路径 / 多部门 | 路径如「模拟集团 / 越南Flyknit / 定型车间(更名)」；兼职用户显示 2 个部门并标记主部门、工号、职务 |
| 扫码登录 | 经真实 Keycloak：登录页出现「企业微信」「钉钉」按钮 → 桥接 → 企业微信扫码地址（扫码步骤为模拟）→ 回调 → Keycloak 首次登录自动建号 → 进入系统，`/auth/me` 返回同步的用户、组织和职务组；同一用户第二次登录正常 |
| 扫码拒绝 | 未同步账号返回 `OIDC_BRIDGE_UNMATCHED`，离职账号返回 `OIDC_BRIDGE_USER_DISABLED` |
| 密码登录兜底 | 为同步用户开通后在 Keycloak 建号并生成 12 位临时密码；直接用临时密码换 token 返回「Account is not fully set up」（需先修改密码，符合预期） |
| `keycloak setup-idp` | 首次执行创建 2 个身份提供方、首次登录流程和服务账号权限；再次执行无重复变更 |
| 页面（Playwright） | 组织同步页显示主数据源和 5 条同步记录；用户页显示多部门与主部门标记、职务、来源，同步用户编辑框只读；部门页按完整路径筛选；知识库授权可按完整路径搜索部门，授权列表显示完整路径 |

## 安全与权限测试（2026-10-09）

以下结果均来自对运行中环境（docker compose 全套容器 + 真实模型）的实际调用，测试账号与测试应用已在测试后清理。

### 开放平台对抗测试

共 67 项，最终 67 项通过。首轮 63/67，失败的 4 项暴露了 2 个真实缺陷，修复后复测通过：

| 缺陷 | 原因 | 修复 |
| --- | --- | --- |
| 伪造 `X-Forwarded-For` 可绕过 IP 白名单 | 生产 uvicorn 信任所有代理转发头，nginx 又是追加而不是覆盖该头 | `frontend/nginx.conf` 改为 `proxy_set_header X-Forwarded-For $remote_addr` |
| 限流 3 次/分钟，顺序请求放过 5 次 | 固定分钟窗口，跨分钟边界可以翻倍 | 改为滑动窗口计数，补充跨边界单测 |

| 类别 | 实测结果 |
| --- | --- |
| 密钥 | 无密钥、格式错误、伪造、改 1 位、大小写翻转、用户 JWT 冒充、SQL 注入串 → 全部 401；吊销、过期分别返回 `API_KEY_REVOKED` / `API_KEY_EXPIRED` |
| 应用状态 | 启用 → 停用 → 启用 → 删除：200 → 403 `API_CLIENT_DISABLED` → 200 → 401 |
| 越权 | 4 篇受限文档：管理员检索命中 9 次，Agent 泄露 0；绑定「知识库管理员」角色不获得超管旁路；请求未授权库返回 403 `KB_NOT_GRANTED`；查询内联 `kb:` 过滤无法越出授权库 |
| 能力 | 未开通问答 / MCP 时调用返回 403 `SCOPE_DENIED` |
| 限流与配额 | 并发 20 次（限 5 次/分钟）恰好 5 次 200、15 次 429；配额 2 次/天：200、200、429 |
| 输出限制 | 返回条数不超过 20（`top_k` 上限），单条内容截断到 2000 字以内（实测最长 1955 字） |
| 提示词注入 | 3 条注入问题：2 条判为超出范围，1 条无依据拒答；受限文档引用 0、机密片段 0 |
| MCP | 非法 JSON 等畸形请求返回的 JSON-RPC 错误码全部符合预期；工具列表随应用开通的能力变化 |
| 管理接口 | 普通用户访问返回 403；调用日志与用量统计一致（21 次调用、2 次错误） |

### 部门与个人权限测试

用 IT运维手册（13 篇文档）验证。新建 5 个真实登录账号：IT、织造车间、保全组长（织造车间下级部门）、整理车间、无部门；
另建 3 个开放平台应用，授权库都是 IT运维手册，代理身份分别绑定 IT、织造车间、整理车间。
每个账号检查知识库列表、4 个检索词的检索结果、指定库检索、库详情、文档详情，并用问答检查引用；最终一轮 58 项全部通过。

| 阶段 | 权限设置 | 能检索到 | 检索不到 |
| --- | --- | --- | --- |
| 1 | 组织内所有人可读 | 全部 5 个账号和 3 个应用 | - |
| 2 | 仅 IT 部门可读 | IT 账号、IT 应用 | 织造车间、保全组长、整理车间、无部门：列表不可见、检索 0 条、指定库检索 0 条、详情 404，问答无依据拒答；织造车间、整理车间应用检索 0 条 |
| 3 | 追加织造车间可读 | 增加织造车间账号、保全组长账号（下级部门继承）、织造车间应用 | 整理车间、无部门、整理车间应用 |
| 4 | 撤销织造车间，单独授权整理车间员工个人 | 增加整理车间员工本人 | 织造车间立即失去访问；整理车间应用仍不可见（个人授权不扩散到部门） |
| 5 | IT 员工调到整理车间，再调回 | 调回后立即恢复 | 调出后立即失去访问 |
| 最终 | 恢复为组织内所有人可读 | 全部 5 个账号和 3 个应用 | - |

### 权限变更生效时间

测试中发现：从「仅部分人可读」放开时，之前查过的同一个问题要等约 60 秒才能检索到（检索结果缓存 60 秒，
缓存 key 包含权限范围，但不感知知识库 ACL 的变化）。收回权限不受影响，因为返回前会用 PG 二次校验。

修复：索引 worker 把新 ACL 写入 Qdrant / OpenSearch 后，递增组织级的结果缓存代次（`retrieval:res-gen:{org_id}`，
是缓存 key 的一部分），旧缓存随即失效。代次在索引更新之后才递增，避免中间的检索把旧结果重新缓存。

修复后实测（同一个问题先查一次写入缓存，再修改权限，每 0.2 秒轮询，各 3 次）：

| 操作 | 修复前 | 修复后 |
| --- | --- | --- |
| 仅 IT → 组织内所有人可读（放开） | 59.5 s | 1.79 s / 1.61 s / 1.60 s |
| 仅 IT → 追加织造车间（部门授权） | - | 0.30 s / 0.32 s / 0.34 s |
| 组织内所有人可读 → 仅 IT（收回） | - | 0.03 s / 0.03 s / 0.02 s |

放开后的 1~2 秒是 outbox → worker 更新索引的时间。

### AI 助手页面测试（Playwright，1440×900）

| 场景 | 结果 |
| --- | --- |
| 新会话连续发 3 个问题 | 距底部最大 1 px，没有跳回顶部，外层布局和窗口都没有滚动 |
| 生成中手动滚到顶部 | 内容继续增长 555 px，滚动位置保持在顶部不被拉回，出现「回到底部」按钮 |
| 点击「回到底部」 | 距底部 0 px，之后继续跟随输出 |
| 思考过程 | 显示 4 个步骤及耗时：理解问题 1.1 s、检索知识库 364 ms（召回 8 个片段 / 5 篇文档）、筛选与校验证据 7 ms、生成回答 4.6 s（首字 583 ms） |
| 停止生成 | 点击后 40 ms 恢复可输入，显示「已停止生成」，可重新生成 |

### 自动化测试

- 后端 pytest 243 项通过（含开放平台 16 项、权限放开立即生效的回归测试），ruff、mypy 无问题。
- 前端 vitest 51 项通过。
