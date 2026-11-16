# 全量不足整改任务板

> 来源：2026-11-14 浏览器全量冒烟 + 生产就绪审计 + system-overview §11。  
> 原则：**现在就改、现在就测**；每项独立可验收，完成即勾选。  
> 概念层历史项保留在文末「已完成归档」。

---

## 执行约定

1. 先勾选「进行中」再改代码；合并前本地跑相关 pytest / 浏览器冒烟。
2. 大项拆子任务；不能在单机一次做完的（如真实双机 HA）也要有**可交付的阶段性产物**（脚本、文档、compose profile、门禁）。
3. 「明确不做」单独列出，避免范围蔓延。

---

## A. 质量与评测（高 · 现在就做）

- [x] **A1 扩充离线评测集 ≥100 题**  
  `retrieval_gold.jsonl` 扩至 **166** 题（中/英/越模板 + rankings）；脚本 `backend/scripts/expand_retrieval_gold.py`。
- [x] **A2 本地跑通评测门禁并固化基线**  
  `eval gold-check` 0 fail；`eval graph-gate` passed；纪要 [`docs/testing/eval-gate-20261114.md`](docs/testing/eval-gate-20261114.md)。
- [x] **A3 问答概念命中 vs 主检索对齐（阶段 1）**  
  提高默认 `retrieval_ko_rrf_weight=2.0`、`retrieval_ko_rerank_bonus=0.15`。浏览器复测：织机题出现「相关概念」与 KO 引用。
- [x] **A4 站内真实模型基线扩展 ≥120**
  夹具 138 题；数据集「真实模型基线扩展」已导入；真实模型+裁判跑 `f202ca889cfb45e7b76d26eb3d4e6153`（可答 Recall@5=1.0，faith≈0.997，库外 19 拒答+5 软拒答）；纪要与推广口径 [`docs/testing/eval-baseline-expand-20261116.md`](docs/testing/eval-baseline-expand-20261116.md)。

---

## B. 功能缺口（安全 / 检索 / 开放）

- [x] **B1 文档密级进入检索/问答门禁（阶段 1）**  
  hydrate：`restricted` 需 edit、`secret` 需 manage，否则 `dropped.classification`；单测 `test_classification_retrieval.py`。
- [x] **B2 流式问答中途撤权窗口收紧**  
  生成前 + 每 `chat_acl_recheck_every_chars` + 生成后复核；撤权中止续写并以 `ACL_REVOKED_ANSWER` 落库；单测 `test_midstream_acl_revoke_aborts_generation`。残余：已推送 token 无法收回。
- [x] **B3 显式 ACL DENY（可选增强）**  
  `resource_acl.effect=allow|deny`；deny-wins（含 inherit 下文档 DENY）；KB manage 可越过文档 DENY。ADR [`docs/adr/0002-explicit-acl-deny.md`](docs/adr/0002-explicit-acl-deny.md)；测例 `test_acl_deny.py`；AclEditor / 文档拒绝名单。索引 `must_not` 留二期。
- [x] **B4 术语 ↔ OpenSearch synonyms 同步**  
  `terminology sync-synonyms` / `POST /admin/terminology/synonyms/sync` 将启用术语写入 `synonyms.txt` 标记区块并热加载；术语表「同步同义词」按钮；与查询侧别名扩展并存。
- [x] **B5 企微 / 钉钉群机器人（问答入口）**  
  `POST /integrations/{wecom,dingtalk}/bot` + WeCom GET echo stub；共享 token + `INTEGRATIONS_BOT_OPEN_API_KEY` 走 Open API `chat`；`format_bot_reply` 带引用摘要。文档 [`docs/ops/group-bots.md`](docs/ops/group-bots.md)；单测 `test_integrations_bot.py`。阶段 1 不加解密/出站。
- [x] **B6 受控库默认策略模板**  
  新建知识库可选「受控库」模板：水印 + 禁复制 + 下载需 edit + 仅授权成员。
- [x] **B7 批量重新处理 / 出页图看板**  
  `POST /knowledge-bases/{kb}/documents/reprocess` + CLI `documents reprocess`；KB 详情多选批量 +「缺页图」筛选；parse 写入 `page_images`/`page_image_expected`/`page_image_error` 并在列表展示。测例 `test_batch_reprocess_failed_filter`、`test_page_images_meta`。
- [x] **B8 结构化镜像 → 真实 ERP/MES 连接器（阶段 1）**  
  `meta.connector=csv|rest` + CLI `structured sync` / `POST …/sources/{id}/sync`；upsert `equip_*`；scheduler 按 `sync_interval_minutes` 入队。文档 [`docs/ops/structured-connectors.md`](docs/ops/structured-connectors.md)；测例 `test_structured_sync.py`。不做 Ontop。

---

## C. UI / UX 不足

- [x] **C1 空状态统一（阶段 1）**  
  `EmptyState` 组件；术语表 / 收藏 / 知识缺口表已接入。其余管理表陆续替换。
- [x] **C1b 空状态统一（阶段 2）**  
  用户 / 用户组 / 审计 / 知识库列表 / KB 文档表 / 开放平台客户端 / 通知 / 搜索 / 结构化数据 / AI 助手历史 接入 `EmptyState`（含可操作 CTA 的入口）。
- [x] **C2 术语页「本体说明」入口**  
  术语表页头「本体说明」对话框（OWL 合约摘要）。
- [x] **C3 管理侧栏按角色折叠/分组**  
  管理下分出「平台工程」子菜单（索引/模型/检索策略/评测/开放平台），默认折叠；仅当前路由落在其中时自动展开。无平台权限时整组不出现。
- [x] **C4 关键移动端适配（阶段 1）**  
  `AppLayout` ≤768px：侧栏可滑出/收起、主区缩边距。
- [x] **C5 界面越语包（vi）**  
  语言菜单含 Tiếng Việt；Element Plus 官方 vi；各 `i18n/locales/*.ts` 已补齐 `vi`（与 en 同键）；Tour `tours.vi.ts` 为越南文。顶栏短标 `中/EN/VI`；vue-i18n fallback：`vi→en→zh-CN`。
- [x] **C5b 使用说明 manual.vi 全量越南文**  
  `manual.vi.ts` 已按 en/zh-CN 结构全量改写为产品越南文（含概念层 / 运营 / 管理 / FAQ）；`content.spec.ts` 5/5 通过。
- [x] **C6 问答发送钮与输入事件**  
  发送钮仅在 streaming 时禁用；`sendFromComposer` 先从 DOM 同步再发送。
- [x] **C7 无障碍基线（阶段 1）**  
  问答发送钮补 `aria-label`；其余主流程 a11y 继续迭代。

---

## D. 运维 / 单机企业就绪

- [x] **D1 备份恢复演练纪要（本机）**  
  `docs/testing/backup-drill-20261114.md`：ekb dump→临时库 restore（42 docs / 1384 chunks），合计 ~20s；keycloak dump 可读。
- [x] **D2 告警通道可验证**  
  `deploy/observability/verify-alerts.{sh,ps1}`：`promtool`/`amtool` + compose profile；纪要 [`docs/testing/alert-channel-20261114.md`](docs/testing/alert-channel-20261114.md)；步骤 [`docs/ops/alerting-smoke.md`](docs/ops/alerting-smoke.md)。本机 **10** 条规则 SUCCESS。
- [x] **D3 暴露面检查清单落地**  
  `docs/ops/exposure-checklist.md` + `docker-compose.yml` 数据面端口/OS 安全注释。
- [x] **D4 单机 HA 阶段方案**  
  ADR [`docs/adr/0003-single-node-ha-stages.md`](docs/adr/0003-single-node-ha-stages.md)：阶段 0–3，明确不做假 HA；`outbox-dispatcher`/`scheduler` 保持单实例。可选 API 扩副本：`deploy/docker-compose.ha-api.yml` + `nginx/frontend-ha.conf`（`--scale backend=2`）。
- [x] **D5 PII / ClamAV 生产开关核查**  
  [`docs/ops/pii-clamav.md`](docs/ops/pii-clamav.md)：默认关、生产建议（输出脱敏优先、ClamAV 有上传面时开）；本地/Compose 样例。`.env.prod.example` / `.env.prod.server.example` / `.env.example` / `backend/.env.example` 注释；`deployment.md` §6 已链。

---

## E. 明确不做 / 低优先级搁置

- [ ] ~~Wiki 多人实时光标协同~~ → **不做**（定位不同）
- [ ] ~~截屏物理防泄漏~~ → **不做**（水印 + 制度）
- [ ] ~~RDF 三元组库 / SPARQL / Ontop / Neo4j~~ → **不做**（已定）
- [ ] 多工厂强隔离正式方案 → 列入 D4 之后评估，本板不展开实现

---

## 建议执行顺序（整改队列）

1. A1 → A2 → A3（质量现在就测）
2. C1 → C2 → C6 → C4 → C5 → C3 → C7（UI 快赢）
3. B1 → B4 → B6 → B2 → B5 → B7 → B8 → B3（功能）
4. D1 → D3 → D2 → D5 → D4（运维）

---

## 已完成归档（概念层）

- [x] P0 术语表 + 别名扩展 + IT 种子
- [x] P0-1 Chunk `entity_ids` + retag CLI
- [x] P0-3 KO 类型 + `ko_relations`
- [x] P1-1 图多跳 RRF + ACL
- [x] P2 评测 18 道多跳金标 + graph-gate
- [x] P1-2 / P1-2b 结构化设备与可扩展域
- [x] P1-3 Open API entity/graph
- [x] P1-4a/b/c 种子挂接、问答相关概念、管理端关系预览
- [x] P2 OWL 合约（无 SPARQL）
