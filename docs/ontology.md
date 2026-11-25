# 企业知识本体（OWL TBox）

> 合约优先：用 OWL 描述「有哪些类、有哪些关系」；**运行时实例（ABox）仍在 PostgreSQL**。  
> 本批**不上** RDF 三元组库、**不提供** SPARQL 端点。  
> Ontology **不是**普通知识文档，**不靠** RAG 检索字段定义；Agent 经 MCP/Open API 结构化工具消费。

## 谁维护（分角色）

| 层 | 谁 | 说明 |
| --- | --- | --- |
| **平台核心 TBox** | 平台 / 开发 | ISA-95 骨架、关系枚举、硬约束、仓库内 `enterprise.ttl`；变更走枚举→TTL→`ontology validate` |
| **组织语义层（Semantic Layer）** | 业务管理员 / Steward | 表/列 ↔ 业务实体与属性（中文名、解释、类型）、映射审核；阶段二 **Ontology Studio** |
| **运行时 ABox** | MES/EAM 同步 + 管理员 | 设备/工单/备件等实例；`structured_*` / `equip_*` / `object_relations` |
| **已发布契约** | Steward 点发布 | Agent **只读 published** 版本；草稿对 MCP 不可见 |

原则：开发不手填每张业务表字段；未审核 AI 建议不进生产；所有 Agent 共用同一份已发布语义。

## 文件

| 路径 | 用途 |
| --- | --- |
| [`ontology/enterprise.ttl`](../ontology/enterprise.ttl) | 平台 TBox：类层次 + KO/工业关系对象属性 |
| [`ontology/examples/seed-abox.ttl`](../ontology/examples/seed-abox.ttl) | 只读演示实例（织机 / EQ-LOOM-01 / 种子 KO），供 Protégé 预览 |
| [`backend/app/ontology/`](../backend/app/ontology/) | 枚举目录、TTL 校验、属性 schema、关系硬/软约束 |
| 迁移 `0031` + `models/semantic.py` | 组织语义：`semantic_model_versions` / entities / attributes / mappings（OS1） |
| `/admin/ontology/*` | Steward 草稿、Approve、发布；见 [TASK.md](../TASK.md) OS1–OS4 |

命名空间：`https://flyknit.local/ontology/enterprise#`（可按组织替换，改 TTL 与 `catalog.NS` 时需同步）。

## 与 PostgreSQL 的映射

| OWL | 代码 / 表 |
| --- | --- |
| `TerminologyEntity` 及子类 `Device` / `Component` / `FailureMode`… | `TerminologyEntityType` → `terminology_entities` |
| `KnowledgeObject` 及 `Faq` / `Device` / `FailureMode`… | `KoType` → `knowledge_objects` |
| `relatedTo` / `partOf` / `dependsOn` / `causes` / `mitigates` / `appliesTo` | `KoRelationType` → `ko_relations` |
| `EquipmentDomain` / `GenericDomain` | `StructuredDomainKind` → `structured_domains`（`equipment` → OWL `EquipmentDomain`，避免与 ISA-95 `Equipment` 冲突） |
| `Device` / `WorkOrder` / `SparePart` | `StructuredObjectType` → 专用 `equip_*` 表 |
| `IndustrialObject` 及 `Site` / `Area` / `Line` / `Equipment` / `Component` / `Material` / `Operation` / `ProcessParameter` / `FailureMode` / `Event` | `StructuredObjectType`（O1.1 合约；落 `structured_records`） |
| `hasPart` / `locatedIn` / `hasFailureMode` / `causedBy` / `consumes` / `workOrderFor` / `spareFor` | `ObjectRelationType` → `object_relations`（O2.1） |
| `linkedToTerminology` / `linkedToKnowledgeObject` | `structured_entity_links` |
| `hasAlias` / `externalId` | `terminology_aliases` / 镜像 `external_id` |

约定：**TBox = OWL 文件；ABox = PG**。检索、问答、开放平台仍走现有 REST/MCP，不读 TTL。

## 用 Protégé 打开

1. 安装 [Protégé](https://protege.stanford.edu/)。
2. 打开 `ontology/enterprise.ttl`，查看 Classes / Object properties。
3. （可选）再打开或合并 `ontology/examples/seed-abox.ttl` 查看演示个体。  
   重新生成样本：`python -m app.cli ontology export-sample`。

## 校验与演进

```bash
cd backend
python -m app.cli ontology validate
pytest tests/test_ontology_contract.py -q
```

演进顺序：

1. 先改 Python `StrEnum`（及必要的 Alembic / API）。
2. 同步改 `ontology/enterprise.ttl` 中对应类或属性。
3. 跑 `ontology validate` 与合约测试；失败则 CI/本地不可合并。
4. 再写入业务数据或种子。

`generic` 域在 OWL 中本地名为 `GenericDomain`；`equipment` 域为 `EquipmentDomain`（见 `catalog._CLASS_OVERRIDES_BY_ENUM`）。  
ISA-95 / FMEA 工业类见 `INDUSTRIAL_OBJECT_CLASSES`（O1.1）。

## 类型化属性 schema（O1.2）

| 产物 | 路径 |
| --- | --- |
| 定义 + 校验 + JSON Schema 导出 | `backend/app/ontology/attributes.py` |
| 管理 API | `GET /admin/structured/attribute-schemas`、`GET /admin/structured/attribute-schemas/{object_type}` |
| 写入门禁 | `POST /admin/structured/records` 对已注册类型严格校验 `attrs` |

规则（已注册类型，硬拒绝）：

- 数量字段必须是 `{value, unit}`，禁止裸数字；缺单位拒收。
- 越上下限拒收；未知属性键拒收（避免关键字段塞进无 schema 的自由 JSON）。
- 未注册类型（如自定义 `recipe`）不校验，保持兼容。
- `device` / `work_order` / `spare_part` 的 schema 约束的是 `meta` 扩展字段（列字段仍权威）；当前 API 主要在 `structured_records.attrs` 上强制执行。

```bash
cd backend
pytest tests/test_structured_attrs.py -q
```

## 工业记录表扩展（O1.3）

- 迁移 `0029`：`structured_records.parent_object_type` / `parent_external_id` + 父级索引；`structured_entity_links.object_type` 扩至 64。
- 工业类型可写入 **equipment** 域；自定义类型仍仅 **generic** 域。
- 创建时从 attrs（如 `line_external_id`）自动派生父级列；`GET /admin/structured/records/children` 按父查询。
- 回滚：`alembic downgrade 0028`。

## 有向对象关系（O2.1 / O2.2）

- 表 `object_relations`（迁移 `0030`）：有向边连接 `terminology` / `ko` / `structured`。
- API：`GET|POST /admin/structured/object-relations`、`DELETE …/object-relations/{id}`。
- 管理端：结构化数据页选中行 →「有向关系」卡片（创建/列表/删除；非法 domain/range 提示拒收）。
- **硬校验**（试点核心，非法 domain/range 直接拒写）：`hasPart`、`hasFailureMode`、`causedBy`、`workOrderFor`、`spareFor`。
- **软告警**（仍可写入，`warnings` + 审计 `ontology_warnings`）：`locatedIn`、`consumes`。
- 规则见 `backend/app/ontology/constraints.py` → `validate_object_relation_endpoints`。

```bash
cd backend
pytest tests/test_object_relations.py -q
```

## KO 关系软约束

创建 KO 关系时，服务层按文档化建议检查类型配对（如 `causes` 建议 `defect → device|process`）。  
**仅返回 `warnings` 并写入审计字段 `ontology_warnings`，默认不硬拦**，以免打断种子与金标。

## 有向图遍历（O3）

- KO：`app/retrieval/graph.py` — `direction=out|in|both`，返回 `path`；默认 `both` 兼容旧检索。
- 工业对象：`app/retrieval/object_graph.py` — 默认出边，支持边类型过滤。
- 诊断扩展：`app/retrieval/diagnosis.py` — 对象出边 + KO causes/depends_on 出边 + mitigates 入边；KO 邻居经 `KoAccess` ACL 后再可作证据。

```bash
cd backend
pytest tests/test_graph_retrieval.py tests/test_diagnosis_graph.py -q
```

## Open API / MCP 本体工具（O4）

| 工具 | REST | 说明 |
| --- | --- | --- |
| `describe_ontology` | `GET /open/ontology/describe?scope=&version=` | 默认 `summary`（无全量 attrs）+ `published`；`all`/`attributes` 才带 attrs |
| （便利） | `GET /open/ontology/published` | `scope=all&version=published` |
| `get_object` | `POST /open/objects/get` | 结构化对象 + 邻居 |
| `query_objects` | `POST /open/objects/query` | 按类型与试点字段筛选 |
| `traverse` | `POST /open/graph/walk` | KO 或 object 有向遍历 |
| `graph_traverse` | `POST /open/graph/traverse` | KO 遍历（现支持 direction） |

均需 API Key 的 `entity` scope。实现：`services/open_api/ontology_tools.py`。  
**禁止**把字段定义写成可检索文档替代上述工具；**禁止**每次无差别返回全部本体（OS1 起按 scope 裁剪）。

```bash
cd backend
pytest tests/test_ontology_tools.py -q
```

## Ontology Studio 与发布版本（阶段二 · OS*）

工作流（对齐 Steward 审核台，非 RDF）：

1. **连接数据库 / 导入 schema（OS2）**：管理端「Ontology Studio → 连接数据库」，引擎支持 **MySQL / PostgreSQL / SQL Server / MongoDB**（可复用「结构化数据」里同类型数据源；Mongo 字段由样本文档推断）。也可粘贴 tables/columns JSON 导入。  
2. AI 生成实体/属性中文名与类型建议（OS3）  
3. Steward Approve / Reject；「Represented by column」确认原始编码↔业务含义  
4. 发布 `semantic_model_versions`（OS1）；一组织一 active published  
5. Agent/MCP 自动读最新 published；平台核心类仍来自仓库 TBox，与组织扩展合并视图  

前端（OS4）：实体列表 + 属性表 + 批量审核 + 连接库向导 + 发布 + 语义证据 + 属性计算口径。另有「跨系统身份」「规则与动作」管理台。操作步骤见应用内使用说明「管理后台」。连接器参数见 [`ops/structured-connectors.md`](ops/structured-connectors.md)；四能力入口见 [`ops/semantic-center.md`](ops/semantic-center.md)。  
实例增量同步（S1）须在该源映射发布之后。

## 明确不做

- Jena / GraphDB / Blazegraph、SPARQL endpoint、Ontop、Collibra 商店  
- 把问答或检索切到 RDF；Neo4j  
- 用 RAG 检索代替本体结构化查询  
- 未审核 AI 建议直接改平台硬约束或写入生产 ABox
