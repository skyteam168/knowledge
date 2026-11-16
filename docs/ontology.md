# 企业知识本体（OWL TBox）

> 合约优先：用 OWL 描述「有哪些类、有哪些关系」；**运行时实例（ABox）仍在 PostgreSQL**。  
> 本批**不上** RDF 三元组库、**不提供** SPARQL 端点。

## 文件

| 路径 | 用途 |
| --- | --- |
| [`ontology/enterprise.ttl`](../ontology/enterprise.ttl) | TBox：类层次 + KO 关系对象属性 + 结构化挂接属性 |
| [`ontology/examples/seed-abox.ttl`](../ontology/examples/seed-abox.ttl) | 只读演示实例（织机 / EQ-LOOM-01 / 种子 KO），供 Protégé 预览 |
| [`backend/app/ontology/`](../backend/app/ontology/) | 枚举目录、TTL 校验、关系软约束 |

命名空间：`https://flyknit.local/ontology/enterprise#`（可按组织替换，改 TTL 与 `catalog.NS` 时需同步）。

## 与 PostgreSQL 的映射

| OWL | 代码 / 表 |
| --- | --- |
| `TerminologyEntity` 及子类 `Device`… | `TerminologyEntityType` → `terminology_entities` |
| `KnowledgeObject` 及 `Faq` / `Device`… | `KoType` → `knowledge_objects` |
| `relatedTo` / `partOf` / `dependsOn` / `causes` / `mitigates` / `appliesTo` | `KoRelationType` → `ko_relations` |
| `Equipment` / `GenericDomain` | `StructuredDomainKind` → `structured_domains` |
| `Device` / `WorkOrder` / `SparePart`（结构化） | `StructuredObjectType` |
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

`generic` 域在 OWL 中本地名为 `GenericDomain`（见 `catalog._CLASS_OVERRIDES`）。

## 关系软约束

创建 KO 关系时，服务层按文档化建议检查类型配对（如 `causes` 建议 `defect → device|process`）。  
**仅返回 `warnings` 并写入审计字段 `ontology_warnings`，默认不硬拦**，以免打断种子与金标。

## 明确不做

- Jena / GraphDB / Blazegraph、SPARQL endpoint、Ontop  
- 把问答或检索切到 RDF  
- Neo4j
