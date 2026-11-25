# Spec: 工业级 Ontology 能力标准（29 项自检）

> 最终验收以本文清单 **29/29** 为准。未勾选项不得宣称「企业级 / 工业级 Ontology 已完成」。

## 目标

在现有 Knowledge Base + Ontology Studio + MCP 上，把 Ontology 从「Semantic 试点」升级为可支撑工业运营与 Agent 受控执行的业务模型（Semantic + Kinetic + Security），**不上** RDF/SPARQL/Neo4j，**不**用 RAG 替代结构化语义查询。

## 标尺来源

- Palantir：Semantic（Object/Property/Link）+ Kinetic（Action/Function）+ Security
- 择优：Playground（可视化）、OpenMetadata（治理/Custom Property）、DataHub（术语层级）、自研（Canonical ID / 工业关系 / MCP / Action）

## 基线（2026-11-25）→ 收口（Wave C）

| 分组 | 勾选 | 说明 |
| --- | --- | --- |
| 1 业务语义 | **5 / 5** | 类型/实例、单位/枚举/i18n、状态机、关系基数、术语层级 |
| 2 数据与身份 | **6 / 6** | Canonical + 多系统 ID + 匹配冲突 + SoT/新鲜度 + 历史 valid-time |
| 3 业务执行 | **6 / 6** | 规则引擎 + ActionType/Runtime + 幂等 + 审批 + 事件/时序 |
| 4 安全与治理 | **6 / 6** | 身份 + 字段/关系 ACL + Action scope + 审计发布回滚 + owners/日志 |
| 5 AI 与开发者 | **6 / 6** | 查询 API + MCP 语义/实体 + MCP Action + SDK + 画布 |
| **合计** | **29 / 29** | 可对外表述「工业级 Ontology（Semantic + Identity + Governance + Kinetic）」 |

## 工业级 Ontology 能力自检（验收清单）

### 1. 业务语义
- [x] 实体类型与实例分离
- [x] 字段语义、类型、单位、枚举和多语言
- [x] 关系类型、方向、基数和关系属性
- [x] 业务术语、别名和同义词
- [x] 状态模型和合法状态转换

### 2. 数据与身份
- [x] 统一 Canonical Entity ID
- [x] 多系统外部 ID 映射
- [x] 实体匹配、去重和冲突处理
- [x] 多数据源映射与权威来源
- [x] 数据血缘、质量和新鲜度
- [x] 历史数据和有效时间管理

### 3. 业务执行
- [x] 业务规则与约束
- [x] Action 定义和参数 Schema
- [x] 前置条件、校验和执行结果
- [x] 事务、幂等、重试和补偿
- [x] 工作流、审批和人工确认
- [x] 事件与时序数据处理

### 4. 安全与治理
- [x] 用户、角色、组织和 Agent 身份
- [x] 对象、字段、关系级权限
- [x] Action 执行授权
- [x] 运行时权限校验
- [x] 审计、版本、审核、发布和回滚
- [x] 数据和日志访问治理

### 5. AI 与开发者生态
- [x] Ontology 查询 API
- [x] MCP 语义查询和实体解析工具
- [x] MCP Action 调用和结果回传
- [x] Agent 上下文和权限传递
- [x] 可视化模型管理工具
- [x] 测试、监控、发布和 SDK

## 门禁映射

| 门禁 | 最低勾选要求 | 对应波次 |
| --- | --- | --- |
| GATE-2 收口 | 组 1 术语项、组 5 查询/MCP 语义、组 4 版本发布；S6 过线 | Wave A 尾 |
| GATE-I1（工业语义+身份） | 组 1 全勾 + 组 2 前 4 项 | Wave A–B |
| GATE-I2（治理+时序） | 组 2 后 2 项 + 组 4 除 Action 外 | Wave B |
| GATE-3 / GATE-I3（执行） | 组 3 全勾 + 组 4 Action 项 + 组 5 MCP Action | Wave C ✅ |
| **工业级宣称** | **29/29** | 全部波次完成 ✅ |

## 明确不做（全程）

- Jena / GraphDB / SPARQL / Neo4j 作为运行时
- 把字段定义写成可检索文档替代 MCP
- 未过 GATE-I1 就开放外部 Agent 写操作
- 无审批的高风险 Action 直写 MES
