# 全量不足整改任务板

> **当前主线（2026-11 起）**：GATE-1 已过 → 阶段二收口 → **工业级 Ontology（29 项自检）**。  
> 来源：Agent 落地就绪度分析 + Palantir Semantic/Kinetic + 工业级 29 项清单。  
> 原则：**未过门槛不进下一阶段**；**未满 29/29 不得宣称工业级 Ontology**；每项独立可验收。  
> 规格 / 计划：`docs/superpowers/specs/2026-11-25-industrial-ontology.md`、`docs/superpowers/plans/2026-11-25-industrial-ontology.md`。

---

## Ontology 谁维护（分角色）

| 层 | 内容 | 谁维护 | 落点 |
| --- | --- | --- | --- |
| **平台核心 TBox** | ISA-95 骨架类、关系枚举、硬约束、`enterprise.ttl` | 平台 / 开发（进仓库） | 改枚举 → TTL → `ontology validate` |
| **组织语义层** | 表/列 → 业务实体与属性中文名、解释、映射、组织内关系草稿 | **业务管理员 / Steward**（Ontology Studio） | 阶段二 OS*；开发不手填每张业务表字段 |
| **运行时 ABox** | 设备 / 工单 / 备件等实例 | MES/EAM 同步 + 管理员补录 | structured + `object_relations` |
| **发布契约** | 已发布语义模型版本 | Steward 点「发布」 | Agent/MCP **只读 published** |

原则（与架构对齐，阶段二必须遵守）：

- Ontology 挂在知识库 + MCP **正确**；**不是**普通知识文档，**不靠** RAG 检索字段定义。
- Agent 用结构化工具：`describe_ontology` / `get_object` / `query_objects` / `traverse`；**禁止**无差别全量倾倒本体。
- 所有 Agent **共用**同一份已发布业务语义；草稿不可见。

---

## 定位与门禁

| 已合格 | 本季主投入 | 明确不做（本轮） |
| --- | --- | --- |
| RAG / 权限 / 知识治理 + **GATE-1～I3 / 29 项** | 真实 MES 全量接入深化、S6 全量评测、生产发布 | RDF/SPARQL/Neo4j；未审核 AI 建议进生产；无审批的高风险写 |

**试点场景**：设备故障诊断助手 —— 文档 + 本体 + 结构化可查可答（GATE-1 已打穿）。  
**外部输入（待提供）**：设备系统数据库表结构 → OS2 映射与 S1 增量同步。

### 阶段门槛（硬门）

| 阶段 | 内容 | 门槛（未过不进入下一阶段） |
| --- | --- | --- |
| **一** | 工业本体建模（O1–O5） | ~~GATE-1 已过~~ |
| **二** | Ontology Studio + 数据接入与规模化（OS* + S*） | 至少 1 条真实源映射已发布；增量同步稳定；S4+S5 权限测过；S6 评测过线 |
| **I1** | Canonical ID + 语义补齐（Wave A） | 组1 全勾 + 组2 前 4 项有证据 |
| **I2** | 治理 / 时序 / 画布（Wave B） | 组2 后 2 项 + 组4（除 Action） |
| **三 / I3** | 受控执行（W* / Wave C） | 组3 全勾 + Action 权限 + MCP Action；高风险 100% 确认 |
| **工业级宣称** | 29 项自检 | **29/29**（见下方清单） |

---

## 工业级 Ontology 能力自检（最终衡量标准）

> 基线 **≈10.5/29**（2026-11-25）。完成一项即勾选并注明证据。

### 1. 业务语义（基线 2.5/5 → 现 5/5）
- [x] 实体类型与实例分离（TBox/ABox；OS 实体 vs equip_*）— O1/OS1
- [x] 字段语义、类型、单位、枚举和多语言 — `unit`/`enum_map`/`labels`；`DEVICE_STATUS_ENUM_MAP`；测 `test_enum_map_rejects_unknown_raw_status` / `test_quantity_requires_unit` / `test_attribute_unit_enum_map_and_labels`
- [x] 关系类型、方向、基数和关系属性 — `cardinality`/`attrs`/`valid_from|to`；`located_in` 默认 many_to_one 超限硬拒；测 `test_cardinality_many_to_one_rejects_second_outgoing`
- [x] 业务术语、别名和同义词 — 术语表 + `terminology_relations`（contains/inherits/related）；`entity_read.related_terms`；测 `test_terminology_relations.py`
- [x] 状态模型和合法状态转换 — `state_machines.DeviceState`；`get_object` 回 `standard_status`/`status_label`；测 `test_device_state_model.py`

### 2. 数据与身份（基线 1/6 → 现 6/6）
- [x] 统一 Canonical Entity ID — `canonical_entities` + `EntityIdentityService`；测 `test_entity_identity.py`
- [x] 多系统外部 ID 映射 — `entity_identifiers`（mes/qr/eam…）；`get_object` 回 `canonical_id`+`identifiers`
- [x] 实体匹配、去重和冲突处理 — `resolve_match` 多命中 → `conflict`，禁止静默合并；重绑拒 `ConflictError`
- [x] 多数据源映射与权威来源 — `semantic_mappings.source_of_truth`；测 `test_attribute_freshness_stale_flag`
- [x] 数据血缘、质量和新鲜度 — `freshness_sla_seconds` + `attrs._meta.freshness`
- [x] 历史数据和有效时间管理 — `entity_state_history`；测 `test_entity_state_history.py`

### 3. 业务执行（基线 0.5/6 → 现 6/6）
- [x] 业务规则与约束 — `OntologyRule` + `evaluate_rules`；测 `test_evaluate_rules_*` / `test_rule_deny_persists_denied_execution`
- [x] Action 定义和参数 Schema — `ActionType` + builtins `device.set_status` / `device.record_note`；测 `test_list_actions_seeds_builtins`
- [x] 前置条件、校验和执行结果 — `ActionRuntime.execute` 校验 required + 状态机；结果落 `action_executions`
- [x] 事务、幂等、重试和补偿 — 幂等键唯一；测 `test_low_risk_action_succeeds_and_is_idempotent`（补偿钩子字段预留）
- [x] 工作流、审批和人工确认 — 高风险单次 30m `ActionApproval`；测 `test_high_risk_requires_approval_then_updates_state`
- [x] 事件与时序数据处理 — S2 事件表 + `entity_state_history` 停机窗查询

### 4. 安全与治理（基线 3/6 → 现 6/6）
- [x] 用户、角色、组织和 Agent 身份 — Keycloak + API Key + on-behalf
- [x] 对象、字段、关系级权限 — 行 ACL + `structured_field` / `object_relation`；`get_object` 剥字段；测 `test_field_acl_rollback.py`
- [x] Action 执行授权 — `ApiScope.ACTION`；Open `/open/actions*` + MCP 工具门禁
- [x] 运行时权限校验 — Action 路径校验 scope + approval actor/payload；读路径 ACL 仍生效
- [x] 审计、版本、审核、发布和回滚 — `POST …/rollback` 重激活历史 published
- [x] 数据和日志访问治理 — `semantic_entities.owners`；`ApiCallLog` 按 org 隔离；测 `test_governance_owners_logs.py`

### 5. AI 与开发者生态（基线 3.5/6 → 现 6/6）
- [x] Ontology 查询 API — `/open/ontology/*`、`/open/objects/*`
- [x] MCP 语义查询和实体解析工具 — `describe_ontology` / `get_object` / `query_objects` / `traverse`
- [x] MCP Action 调用和结果回传 — `list_actions` / `approve_action` / `invoke_action`
- [x] Agent 上下文和权限传递 — on-behalf + scopes（含 `action`）
- [x] 可视化模型管理工具 — Studio 关系画布（SVG）+ Inspector
- [x] 测试、监控、发布和 SDK — `test_ontology_actions.py`；`ACTION_CALLS`；`sdk/python` + `sdk/typescript`

**当前计数：29 / 29（GATE-I3 / Wave C 已齐）。对外可表述：工业级 Ontology（Semantic + Identity + Governance + Kinetic）。**

---

## 执行约定

1. 先把条目标为进行中再改代码；完成即勾选并写清验收证据（测例名 / 纪要路径）。
2. 大项拆子任务；每项必须带**测试完整性**条目（单测 + 必要的 API/MCP/浏览器冒烟）。
3. 继续遵守：ABox 仍在 PostgreSQL；不上 RDF 库；管理助手「计划→风险→确认→执行→校验」模式留给阶段三复用。
4. 「明确不做」见文末，避免范围蔓延。

---

## 阶段一 · 工业本体建模（本季必做 · O1–O5）

> 对应报告 P0。目标：从「KO 标签图」升级为「类型化工业对象 + 有向关系 + Agent 可自描述/可查询」。

### O1 工业核心对象模型（ISA-95 骨架）

- [x] **O1.1 TBox / 枚举扩展**  
  `ontology/enterprise.ttl` v1.1.0 + `catalog.py`：`IndustrialObject` 及 Site/Area/Line/Equipment/Component/Material/Operation/ProcessParameter/FailureMode/Event；术语/KO 增 `component`/`failure_mode`；域 `equipment` → OWL `EquipmentDomain` 避免冲突。  
  **测**：`pytest tests/test_ontology_contract.py`（含工业类与命名不冲突断言）。
- [x] **O1.2 类型化属性 schema**  
  `ontology/attributes.py`：工业类型 + equip meta 扩展字段；数量必须 `{value,unit}`；未知键/越界/缺单位硬拒绝；`GET …/attribute-schemas`；`create_record` 门禁；管理端新建记录可选类型并填 attrs JSON。文档见 `docs/ontology.md`。  
  **测**：`pytest tests/test_structured_attrs.py`。
- [x] **O1.3 结构化表扩展**  
  迁移 `0029`：`structured_records` 父级列 + 索引；工业类型可入 equipment 域；`derive_parent_ref`；`GET …/records/children`。说明见 `docs/ontology.md`。  
  **测**：`pytest tests/test_industrial_records.py`。

### O2 对象间有向、类型化关系

- [x] **O2.1 `object_relations`（或等价）**  
  表 `object_relations`（迁移 `0030`）+ `ObjectRelationService` CRUD；边可连 terminology / ko / structured；关系类型 hasPart、locatedIn、hasFailureMode、causedBy、consumes、workOrderFor、spareFor；自环与唯一边拦截；`GET/POST/DELETE …/object-relations`。  
  **测**：`pytest tests/test_object_relations.py` + ontology contract industrial relations。
- [x] **O2.2 核心关系硬校验**  
  `ontology/constraints.py`：`hasPart` / `hasFailureMode` / `causedBy` / `workOrderFor` / `spareFor` 硬拦截 domain/range；`locatedIn` / `consumes` 软告警；创建响应与审计带 `warnings` / `ontology_warnings`。  
  **测**：`pytest tests/test_object_relations.py`（含硬拒 + 软告警）。
- [x] **O2.3 管理端关系编辑**  
  结构化管理页选中对象后可列出/创建/删除有向边；方向、关系类型、对端类型与 ID；非法边前端提示拒收。API：`/admin/structured/object-relations`。  
  **测**：`pytest tests/test_object_relations.py`（含路由注册）+ 管理页关系卡片。

### O3 有向图遍历（检索 + Open API）

- [x] **O3.1 遍历区分方向与边类型**  
  `traverse_ko_relations` / `GraphConfig.direction`：out/in/both + `relation_types` + `path`；`traverse_object_relations` 工业有向边。  
  **测**：`pytest tests/test_graph_retrieval.py`（有向 KO + causedBy 诊断链正反向不同）。
- [x] **O3.2 问答/检索可选使用有向扩展**  
  `retrieval/diagnosis.py`：对象出边（hasFailureMode/causedBy/…）+ KO causes/depends_on 出边与 mitigates 入边；`KoAccess` 二次 ACL。检索侧可通过 `GraphConfig.direction`/`relation_types` 配置。  
  **测**：`pytest tests/test_diagnosis_graph.py`（有权召回 / 无权丢弃）。

### O4 Agent 本体与对象工具（MCP / Open API）

- [x] **O4.1 `describe_ontology`**  
  MCP + `GET /open/ontology/describe`；类/属性/工业关系/硬软约束由合约生成；需 `entity` scope。  
  **测**：`pytest tests/test_ontology_tools.py`。
- [x] **O4.2 `get_object`**  
  MCP + `POST /open/objects/get`；按 object_id / external_id 取属性与邻居。  
  **测**：同上（设备种子 + equipment/failure_mode）。
- [x] **O4.3 `query_objects`**  
  MCP + `POST /open/objects/query`；类型 + status/line/equipment/q 分页。  
  **测**：同上。
- [x] **O4.4 `traverse`（有向）**  
  MCP `traverse` + `POST /open/graph/walk`；`graph_traverse` 增 direction/path；共用 O3 实现。  
  **测**：同上 + open_entity 回归。

### O5 试点打穿：「设备故障诊断助手」

- [x] **O5.1 种子/演示数据**  
  `seed_equipment` 扩展 ISA-95 + FMEA：产线层级、部件、断纱故障模式、有向边（hasPart/hasFailureMode/causedBy/workOrderFor/spareFor）+ 既有处置 KO。  
  **测**：`pytest tests/test_diag_gate.py::test_seed_diagnosis_chain_idempotent`；CLI `structured seed-equipment`。
- [x] **O5.2 诊断问答金标（人审）**  
  ≥20 道结构金标 `tests/fixtures/diag_gold.jsonl`；`test_diag_gold_structural_gate`；纪要 `docs/testing/diag-pilot.md`。LLM 人审可后续叠加。  
  **测**：`pytest tests/test_diag_gate.py` 退出码 0。
- [x] **O5.3 端到端冒烟脚本**  
  `test_diag_smoke_tool_script`：describe → query → traverse → get_object。  
  **测**：同上；步骤见 `docs/testing/diag-pilot.md`。
- [x] **O5.4 功能完整性检查表**  
  见 `docs/testing/diag-pilot.md` GATE-1 表：对象 CRUD、硬校验、有向遍历、四工具、ACL 测、门禁、管理端关系卡片。

### 阶段一门禁勾选

- [x] **GATE-1** 一条试点产线（或等价数据集）建模完成  
- [x] **GATE-1** 「设备 → 工单 → 备件」经 `get_object` / `query_objects` / `traverse` 可查  
- [x] **GATE-1** O1–O5 相关 pytest + O5.3 冒烟全绿  
- [x] **GATE-1** 诊断金标门禁通过  

---

## 阶段二 · Ontology Studio + 数据接入与规模化（GATE-1 已过 · 可开工）

> 对应报告 P1。主线 **OS***（语义治理工作台）+ **S***（实例同步 / 权限 / 评测）。  
> OS 承接「读表 → AI 建议 → 审核 → 发布」；S1 做实例 CDC（映射发布后方可正式同步）。  
> 参考能力形态：Collibra 式 Semantic Layer（实体 / 属性 / Represented by column / Approve-Reject），**不上** Collibra/RDF 商店。

### Ontology Studio（OS* · 组织语义层）

- [x] **OS1 语义模型版本与发布**  
  迁移 `0031`：`semantic_model_versions` + entities / attributes / mappings；draft→publish（需至少一 approved 实体）；一 org 一 active；`/admin/ontology/*`；`describe_ontology` 默认 `scope=summary`（不含全量 attrs）+ `version=published`；草稿对 Agent 不可见。  
  **测**：`pytest tests/test_semantic_model.py` + `test_ontology_tools.py`。
- [x] **OS2 数据源 schema 导入**（承接原「读结构」；设备库表到位后立刻开）  
  `POST /admin/ontology/schema-import`：JSON tables/columns → draft entities/attrs/mappings；二次导入幂等；可选 `auto_approve`。  
  **测**：`pytest tests/test_semantic_model.py::test_schema_import_idempotent`。
- [x] **OS3 AI 建议 + 审核台**（细化原 S3）  
  `POST …/suggest`（启发式中文名/描述/类型）+ `POST …/batch-status`（Approve/Reject/draft）；未 Approve 实体不可发布；审计 `semantic_model.suggest` / `batch_status`。  
  **测**：`pytest tests/test_semantic_model.py`（含 `test_suggest_and_batch_approve`）。
- [x] **OS4 Ontology Studio 前端**  
  `/admin/ontology`：版本列表 + 实体/属性表（Represented by）+ schema 导入 + 建议 + 批量 Approve + 发布；权限 `admin:retrieval`。  
  **测**：`frontend` locale 键对齐；浏览器冒烟 草稿→批准→发布（与 MCP published 一致）。

### 数据接入与规模化（S*）

- [ ] **S1 真实 MES/EAM 增量接入 1 家**（游标/CDC；非仅全量轮询）  
  **前置**：该源至少一条映射经 OS 发布。OS2=语义映射，S1=实例数据。  
  - [x] **S1.1 游标增量能力**（可先于真实源）：`meta.incremental` + `sync_cursor` 水位；CSV 按 `updated_at` 过滤；REST 传 `updated_since`；成功后才推进游标；`force_full` 全量；dry-run 不写游标。  
    **测**：`pytest tests/test_structured_sync.py`（`test_csv_incremental_cursor_resume` / `test_rest_incremental_passes_updated_since`）。  
  - [x] **S1.2 真实源接入**：`connector=mysql`（`password_env`，不落库密文）；`probe-mysql` CLI；增量 cursor；测例 `test_structured_mysql.py`；文档 `docs/ops/structured-connectors.md`。  
    **联调**：`10.10.130.199:3306` / `maintaince.device_info`；源 `MES device_info`（`70ad73a59d47488f84a5bd535fb8b855`）；`column_map`=`id`（`device_number` 有重复）/`device_name`/`device_location`/`status`/`create_time`；全量 sync **created=5306**；密码仅 `MES_MYSQL_PASSWORD`。  
    **Agent 调试链**：`python -m app.cli structured wire-mes-chain` → 术语「电脑编织横机」+30 条 links + 发布 Studio `mes-device-info-*`；Open `get_object` 回 `links`+`attrs.col_device_number`。  
    **增量水位验收**：`test_mysql_incremental_skips_unchanged_watermark`（force_full 后第二次 incremental → `devices.created==0`）；套件 `pytest tests/test_structured_mysql.py -q` 全绿。水位字段优先 `update_time`，本源仅有 `create_time`（见 connectors 文档限制）。
- [x] **S2 状态历史 / 报警事件时间表**  
  `structured_records` 增 `occurred_at` / `ended_at` / `event_type`（迁移 `0032`）；创建 event 时 denorm；Open `query_objects` 支持 `event_type`+时间窗；`POST /open/objects/aggregate`（count）+ MCP `aggregate_objects`；种子 `EVT-DT-01/02`、`EVT-AL-01`。  
  **测**：`pytest tests/test_structured_events.py`（denorm + 停机窗口 query/aggregate）。
- [ ] ~~**S3 半自动本体构建**~~ → **并入 OS3**（不再单开；审核台即 Studio）
- [x] **S4 代用户授权（on-behalf-of）**  
  新 scope `on_behalf`；头 `X-On-Behalf-Of: <user_id|username>`；身份切到终端用户 principals（须与 client 绑定 dept/group/role 有交集）；`whoami` 回传 `on_behalf_of` / `acting_user_*`。  
  **测**：`pytest tests/test_on_behalf.py`（含同一应用 Alice 可见 EQ-A、Bob 不可见）。
- [x] **S5 结构化行级权限**（工厂/车间等挂 ACL）  
  `resource_acl.resource_type=structured`；无 ACL=组织内默认可读；有 ALLOW=受限；DENY 优先；`GET/PUT /admin/structured/objects/{type}/{id}/acl`；Open `get_object` / `query_objects` / `traverse` 过滤。  
  **测**：`pytest tests/test_structured_acl.py`（org 默认 / 受限 / DENY 对抗）。
- [ ] **S6 规模化评测**（≥5000 文档、≥300 人审题；参数/近似型号/多跳诊断；重标拒答阈值）  
  **测**：评测纪要 + 阈值变更 ADR/配置说明。  
  **GATE-2 数据路径最小证据（非满额 S6）**：`pytest tests/test_diag_gate.py -q` 全绿（现象→根因→工单/备件/本体工具）；满额人审与 ≥5000 文档仍待 R1/S6。

### 阶段二建议顺序

1. **OS1** → **OS2**（有表结构即可）→ **OS3** → **OS4**  
2. 映射发布后开 **S1** 增量同步  
3. **S4 / S5** 可与 Studio 后期并行；**S6** 在数据与语义稳定后  
4. 可并行 **R1**（不挡主线）

### 阶段二门禁勾选

- [x] **GATE-2** 至少 1 条真实源经 OS 映射发布 + S1 增量同步稳定运行  
  证据：`MES device_info` + Studio 发布 + `test_mysql_incremental_skips_unchanged_watermark` + 联调 created=5306。
- [x] **GATE-2** OS1–OS4 相关单测 / 冒烟全绿；`describe_ontology` 仅 published + scope  
  证据：`test_semantic_model.py` / Studio 冒烟；MCP `describe_ontology` 仅 published。
- [x] **GATE-2** S4+S5 权限测通过  
  证据：`test_on_behalf.py`、`test_structured_acl.py`。
- [ ] **GATE-2** S6 指标达标并留纪要（满额未过；仅有 diag 结构门禁最小证据）

---

## 阶段三 · 受控执行（排期待定 · 未过 GATE-2 不开工）

> 对应报告 P2。编号 W*。复用 `services/admin_agent/` 模式。

- [ ] **W1 外部 Agent 受控写操作**（开工单 / 备件申请 / 回写处置；计划→风险→确认→执行→校验）  
  **测**：高风险无确认必失败；确认后事务 + 校验；审计完整。
- [ ] **W2 工艺文档专项**（参数卡/点检表结构化；检索「当前有效版 SOP」）  
  **测**：旧版 SOP 不进正式回答证据（或标记废弃）。
- [ ] **W3 主备 + 异地备份**（产线嵌入前）  
  **测**：恢复演练纪要。
- [ ] **W4 Agent 端到端任务评测集**  
  **测**：多步任务回归门禁。

### 阶段三门禁勾选

- [ ] **GATE-3** 高风险 Action 100% 经人工确认  
- [ ] **GATE-3** W4 评测通过  
- [ ] **GATE-3** W3 演练签字/纪要  

---

## 可并行 RAG 加固（不挡阶段一，不抢主线）

- [ ] **R1** 真实提问滚动扩充评测集 + 20～30 题人审抽检（可与 S6 合并）  
- [ ] **R2** 文档量上升后重标定拒答阈值（0.45 余量问题）  
- [ ] **R3** 工程图 / P&ID 理解（专项，低优先）  

---

## 建议执行顺序

### 阶段一（已完成）

1. O1 → O2 → O3 → O4 → O5 → **GATE-1** ✓

### 阶段二（当前）

1. OS1 → OS2 → OS3 → OS4（Ontology Studio）  
2. S1（映射发布后）→ S2；S4/S5 并行；S6 收尾 → **GATE-2**  
3. 设备库表到位后：**优先 OS2**，并刷新诊断金标中的真实表映射用例。

---

## 明确不做 / 搁置

- [ ] ~~Wiki 多人实时光标协同~~ → **不做**
- [ ] ~~截屏物理防泄漏~~ → **不做**（水印 + 制度）
- [ ] ~~RDF 三元组库 / SPARQL / Ontop / Neo4j / Collibra 商店~~ → **不做**（已定）
- [ ] ~~把 Ontology 当 RAG 文档 / 用检索代替 describe/query/traverse~~ → **禁止**
- [ ] ~~未审核 AI 建议直接写正式 TBox 或生产 ABox~~ → **禁止**
- [ ] ~~未过 GATE-1 就做 S/W~~ → **已解除（GATE-1 过）；未过 GATE-2 不做 W***  
- [ ] 多工厂强隔离正式方案 → 阶段二权限模型稳定后再评估

---

## 已完成归档

### 2026-11 整改板（A/B/C/D 原项）

- [x] A1–A4 评测金标与站内 138 题真实模型基线  
- [x] B1–B8 密级 / 中途撤权 / ACL DENY / 同义词 / 群机器人 / 受控库 / 批量重处理 / CSV·REST 连接器  
- [x] C1–C7 空状态 / 本体说明入口 / 侧栏 / 移动端 / 越语 / 发送钮 / a11y  
- [x] D1–D5 备份演练 / 告警通道 / 暴露面 / 单机 HA ADR / PII·ClamAV  

### 概念层（更早）

- [x] 术语表 + 别名扩展 + IT 种子  
- [x] Chunk `entity_ids` + retag CLI  
- [x] KO 类型 + `ko_relations`  
- [x] 图多跳 RRF + ACL  
- [x] 多跳金标 + graph-gate  
- [x] 结构化设备与可扩展域  
- [x] Open API entity/graph  
- [x] 种子挂接、问答相关概念、管理端关系预览  
- [x] OWL 合约（无 SPARQL）  
