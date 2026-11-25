# 工业级 Ontology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 29 项工业级自检清单，把现有 Semantic 试点升级为可宣称工业级的 Ontology（Semantic + Identity + Governance → Kinetic/Action）。

**Architecture:** ABox 仍在 PostgreSQL；组织语义走 `semantic_model_*` + 术语表；新增 Canonical Entity + identifier mappings；Studio 增强关系/状态；阶段三再加 Action Runtime。Agent 只经 MCP/Open API 读 published 语义与实体，写操作必须过 Action + 权限 + 审计。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、Vue 3 + Element Plus、现有 MCP（`/api/v1/open/mcp`）、Dramatiq（同步/Action 异步可选）。

**Spec:** `docs/superpowers/specs/2026-11-25-industrial-ontology.md`

## Global Constraints

- 不上 RDF 三元组库 / SPARQL / Neo4j 运行时
- Agent **只读 published** 语义；草稿不可见
- 禁止用 RAG 文档替代 `describe_ontology` / `get_object` / `query_objects`
- 未过 GATE-I1 不开外部 Agent 写操作（Action）
- 密码/密钥不进 git；连接器用 `password_env`
- 每任务必须有 pytest；涉及 MCP 的加 Open/MCP 冒烟
- 勾选 29 项时必须在 TASK.md / spec 写清证据（测例名或纪要路径）

## Review Focus

- Canonical ID 与某业务系统主键混淆 → 解析必须返回 `canonical_id` + `identifiers[]`
- 多系统同码不同物 → 冲突状态不可静默合并
- Action 仅包装 MCP tool 无前置条件 → 高风险必须人工确认
- 字段级权限未校验却返回 attrs → get_object 必须剥离无权字段
- 回滚发布后 Agent 仍见旧版 → `describe_ontology` 只跟 active published

---

## Wave A — 收口 GATE-2 + Identity P0（目标：组1部分 + 组2前4 + 组5查询稳）

### Task 1: GATE-2 收口（S6 + 真增量水位）

**Files:**
- Modify: `backend/app/services/structured/connectors/mysql.py`（水位字段优先 `update_time`，无则文档化限制）
- Modify: `docs/testing/diag-pilot.md` 或新建 `docs/testing/ontology-gate2.md`
- Modify: `TASK.md` GATE-2 勾选
- Test: `backend/tests/test_structured_mysql.py`、评测相关现有用例

**Interfaces:**
- Consumes: 现有 `MES device_info` 源、`wire_mes_chain`
- Produces: GATE-2 纪要；增量 sync 第二次 `created≈0`

- [x] **Step 1: 写/补增量验收测例** `test_mysql_incremental_skips_unchanged_watermark`
- [x] **Step 2: Run fail then实现/调整水位策略并 PASS** (`pytest tests/test_structured_mysql.py -q` 5 passed)
- [x] **Step 3: 跑 S6 最小过线集并写 GATE-2 证据到 TASK.md**（`test_diag_gate`；满额 S6 仍开）
- [ ] **Step 4: Commit** `chore: close GATE-2 ontology data path evidence`（待用户要求）

---

### Task 2: Canonical Entity + Identifier Mapping

**Files:**
- Create: `backend/alembic/versions/YYYYMMDD_00xx_canonical_entities.py`
- Create: `backend/app/models/identity.py`（或扩 `structured.py`）
- Create: `backend/app/services/structured/identity.py`
- Modify: `backend/app/services/open_api/ontology_tools.py`（`get_object` / resolve 回传 canonical）
- Modify: `backend/app/schemas/open_api.py`
- Test: `backend/tests/test_entity_identity.py`

**Interfaces:**
- Consumes: `EquipDevice` / `StructuredRecord` 现有行
- Produces:
  - `CanonicalEntity(id, org_id, object_type, display_name, status)`
  - `EntityIdentifier(canonical_id, system, id_kind, external_id, valid_from, valid_to, is_primary)`
  - `resolve_identifier(org_id, system, external_id, object_type) -> CanonicalEntity | Conflict`
  - Open: `get_object` 增加 `canonical_id`, `identifiers`

- [x] **Step 1: 失败测例**（`tests/test_entity_identity.py`）
- [x] **Step 2: 迁移 + 模型 + service 最小实现，测例 PASS**（`0033` + `entity_identity` models + `EntityIdentityService`）
- [x] **Step 3: `get_object` 输出 `canonical_id`+`identifiers`**（`test_get_object_exposes_canonical_id_and_identifiers`）
- [ ] **Step 4: Commit** `feat: canonical entity identifier mapping`（待用户要求）

**勾选推进:** 组2「Canonical ID」「多系统外部 ID 映射」「匹配/冲突」骨架

---

### Task 3: 枚举 / 单位 / 多语言属性契约

**Files:**
- Modify: `backend/app/ontology/attributes.py`
- Modify: `backend/app/models/semantic.py`（属性元数据：unit、enum_map、i18n）
- Modify: `backend/app/services/ontology_studio/service.py`
- Modify: Studio 前端属性表
- Test: `backend/tests/test_structured_attrs.py`、`test_semantic_model.py`

**Interfaces:**
- Produces: 属性定义支持 `unit`, `enum_map: {raw->standard->label}`, `labels: {zh,en,vi}`；写入校验拒绝未知枚举（已注册类型）

- [x] **Step 1: 测例** `test_enum_map_rejects_unknown_raw_status` / `test_quantity_requires_unit`
- [x] **Step 2: 实现并 PASS；Studio 可编辑 enum_map**（迁移 `0034`；Studio 属性对话框 unit/enum_map/labels）
- [ ] **Step 3: Commit** `feat: semantic attribute unit enum i18n`（待用户要求）

**勾选推进:** 组1「字段语义、类型、单位、枚举和多语言」

---

### Task 4: 状态模型（以 Device 为试点）

**Files:**
- Create: `backend/app/ontology/state_machines.py`
- Modify: sync / get_object 标准化 `status` → `standard_status` + `status_label`
- Test: `backend/tests/test_device_state_model.py`

**Interfaces:**
- Produces: `DeviceState = RUNNING|STOPPED|MAINTENANCE|IDLE|UNKNOWN`；`can_transition(from, to) -> bool`；非法转换拒绝（写路径预留，读路径先规范化）

- [x] **Step 1: 测例** 原始 `0/1/2` → 标准态；非法 `RUNNING→MAINTENANCE` 无许可时失败（函数级）
- [x] **Step 2: 实现映射表（可配置）+ get_object 输出标准态**
- [ ] **Step 3: Commit** `feat: device status state machine`（待用户要求）

**勾选推进:** 组1「状态模型和合法状态转换」

---

### Task 5: 关系基数与关系属性

**Files:**
- Modify: `backend/app/models/structured.py`（`object_relations` 增 cardinality / attrs jsonb / valid_from/to 可选）
- Modify: `backend/app/ontology/constraints.py`
- Modify: 管理端关系卡片
- Test: `backend/tests/test_object_relations.py`

**Interfaces:**
- Produces: 创建关系时可声明 `one_to_many` 等；超出基数硬拒；`attrs` 可存关系属性

- [x] **Step 1–3: TDD 实现**（迁移 `0035`；`test_cardinality_many_to_one_rejects_second_outgoing`）
- [ ] **Step 4: Commit** `feat: object relation cardinality and attrs`（待用户要求）

**勾选推进:** 组1「关系类型、方向、基数和关系属性」

---

### Task 6: 术语层级（DataHub 式 Contains / Inherits）

**Files:**
- Create: migration `terminology_relations`
- Modify: `backend/app/services/terminology/service.py`
- Modify: 术语表前端「相关术语」
- Test: `backend/tests/test_terminology_relations.py`

**Interfaces:**
- Produces: `TerminologyRelation(from_id, to_id, kind: inherits|contains|related)`；MCP `entity_read` 返回 related_terms

- [x] **Step 1–3: TDD**（迁移 `0036`；`test_terminology_relations.py`；`entity_read.related_terms`）
- [ ] **Step 4: Commit** `feat: terminology contains inherits relations`（待用户要求；前端「相关术语」卡片可后续补）

**勾选推进:** 组1「业务术语、别名和同义词」升级为完整勾选（含层级）

---

## Wave B — 治理、血缘、时序、可视化（GATE-I2）

### Task 7: 权威来源 / 新鲜度 / 轻量字段血缘

- [x] 实现（迁移 `0037`；`test_attribute_freshness*`；Studio mapping 可设 SoT/SLA）
- [ ] Commit（待用户要求）

### Task 8: Valid Time / 历史快照（设备状态试点）

- [x] 实现（`entity_state_history` / `0038`；`test_entity_state_history.py`）
- [ ] Commit（待用户要求）

### Task 9: Studio 关系画布（Playground 风格最小集）

- [x] SVG 画布 + Inspector（`OntologyStudioView` 表格/画布切换）
- [ ] Commit（待用户要求）

### Task 10: 字段级 / 关系级 ACL + 发布回滚

- [x] `structured_field`/`object_relation` ACL；`rollback_publish`；`test_field_acl_rollback.py`
- [ ] Commit（待用户要求）

### Task 11: Owner / 数据与日志访问治理（OM 轻量）

- [x] `semantic_entities.owners`（`0039`）；`test_governance_owners_logs.py`
- [ ] Commit（待用户要求）

---

## Wave C — Kinetic：规则 + Action + MCP 写（GATE-3 / GATE-I3）

> **前置:** GATE-I1 + GATE-I2；复用管理助手「计划→风险→确认→执行→校验」模式。

### Task 12: 业务规则引擎（只读解释 + 写拦截）

**Produces:** `OntologyRule`（条件 JSON + 优先级）；Action/状态转换前 `evaluate(rules, object) -> allow|deny|require_confirm`  
**勾选:** 组3「业务规则与约束」

- [x] 实现（`ontology/rules.py` + 迁移 `0040`；测 `test_evaluate_rules_*` / `test_rule_deny_*`）
- [ ] Commit（待用户要求）

### Task 13: Action Type + Runtime

**Produces:**
- `ActionType(name, input_schema, preconditions, risk, systems[])`
- `execute_action(type, input, actor, on_behalf) -> ActionResult`
- 幂等键、重试、补偿钩子、审计  
**勾选:** 组3 Action 四项 + 组4「Action 执行授权」「运行时权限校验」

- [x] 实现（`ActionRuntime` + builtins；`ApiScope.ACTION`；`ACTION_CALLS`；测 `test_ontology_actions.py`）
- [ ] Commit（待用户要求）

### Task 14: 工作流与人工确认

**Produces:** 高风险 Action `approval` 单次 30 分钟；与 W1–W4 对齐  
**勾选:** 组3「工作流、审批和人工确认」

- [x] 实现（`ActionApproval` 30m 单次；`/open/actions/approve`；测 `test_high_risk_requires_approval_*`）
- [ ] Commit（待用户要求）

### Task 15: MCP Action + SDK

**Produces:** MCP `list_actions` / `invoke_action`；Python/TS 最小 SDK；监控指标  
**勾选:** 组5「MCP Action」「测试、监控、发布和 SDK」；组5「Agent 上下文和权限传递」确认

- [x] 实现（MCP `list_actions`/`approve_action`/`invoke_action`；`sdk/python` + `sdk/typescript`）
- [ ] Commit（待用户要求）

---

## 执行顺序（硬约束）

```text
Task1 (GATE-2)
  → Task2 (Canonical ID) → Task3 (enum/unit) → Task4 (state) → Task5 (cardinality) → Task6 (术语层级)
  → Task7–11 (治理/时序/画布)  【GATE-I2】
  → Task12–15 (Action)         【GATE-I3 / 29/29】
```

每完成一组，更新：
1. `docs/superpowers/specs/2026-11-25-industrial-ontology.md` 勾选
2. `TASK.md` 对应 GATE / 工业自检计数（x/29）

## 完成定义

- 自检清单 **29/29** 均有证据
- MCP：`describe_ontology` → `query_objects` → `get_object`(含 canonical+identifiers) →（仅 Wave C 后）`invoke_action`
- 对外可表述：**工业级 Ontology（Semantic + Identity + Governance + Kinetic）**
