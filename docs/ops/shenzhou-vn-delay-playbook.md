# 申洲国际越南厂生产异常试点 · 数据登记与操作说明书

> 场景：模拟申洲国际某越南工厂因关键面料短缺导致生产延期，Agent / 结构化本体可查询风险、解析跨系统料号、并在审批后执行跨厂调拨。  
> 实现入口：`backend/app/services/structured/seed_mfg.py`（幂等种子）+ `ontology accept-mfg`（闭环验收）。  
> 默认组织 ID：`default`（与 Keycloak `org_id` / 本地默认一致时可省略）。

---

## 0. 业务故事（一句话）

品牌客户订单 **PO-1001** 交期仅剩约 2 天 → 越南生产工单 **MO-2001** 计划 10000 / 已完成 6000 / 缺关键料 1000 kg → 设备 **EQ-4001** 运行中但等料 → 越南仓仅 **200 kg**、宁波仓富余 **2200 kg** → 生产经理 **EMP-001** 可发起跨厂调拨（需审批）→ SOP 知识条目说明标准处置。

依赖链（自上而下）：

```
CustomerOrder PO-1001 (at_risk)
  └── ProductionOrder MO-2001 (at_risk, shortage_qty=1000)
        ├── Line LINE-01 @ Factory FAC-VN-SZ
        ├── Equipment EQ-4001 (waiting_material)
        ├── Material MAT-3001  ←→  跨系统身份 (ERP / WMS)
        ├── Inventory INV-VN-MAT-3001 (200) / INV-NB-MAT-3001 (2200)
        └── Employee EMP-001 (can_request_transfer)
```

---

## 1. 快速落库（推荐：一键种子）

适用于演示、联调、回归。种子幂等，可重复执行。

### 1.1 前置条件

1. 全套容器已启动（`make up` 或 `docker compose -f deploy/docker-compose.yml up -d`）。
2. 后端健康：`http://localhost:8000/ready`（或本机映射端口，如 `18000`）。
3. 库中至少有一个知识库（种子会尝试写入 SOP 知识条目；若无 KB 则跳过 KO，不影响结构化对象）。
4. 登录账号属于目标组织（演示常用 `alice` / `password`，`org_id=org-demo` 时请用 `--org org-demo`）。

### 1.2 执行种子

```bash
# 容器内（推荐）
docker compose -f deploy/docker-compose.yml exec backend \
  python -m app.cli structured seed-mfg --org default

# 验收闭环（再跑种子 + 身份/查询/动作/审计门禁）
docker compose -f deploy/docker-compose.yml exec backend \
  python -m app.cli ontology accept-mfg --org default --user alice
```

成功时种子返回计数（`sources` / `domains` / `records` / `object_relations` / `identifiers` / `terms` / `kos`）；`accept-mfg` 输出 JSON，`ok: true` 且 `failed: []`。

### 1.3 种子写入了什么

| 类别 | 名称 / 编号 | 说明 |
| --- | --- | --- |
| 数据源 | `制造试点 Fixture` | `type=wms`，`meta.seed=true`，`fixture=shenzhou-vn-delay` |
| 业务域 | `mfg` / 制造试点 | `kind=generic` |
| 术语 | 针织关键面料-3001 | 别名含 `MAT-3001`、`YN-MAT-3001`、旧料号等 |
| 结构化对象 | 见第 2 节 | 全部挂在该源 + 域下 |
| 有向关系 | 见第 3 节 | `object_relations` |
| 跨系统身份 | 见第 4 节 | Canonical + 多系统 external_id |
| 知识条目 | 【种子】跨厂物料调拨 SOP… | 发布态 POLICY，供 RAG 对照 |

兼容旧验收脚本的编号仍会写入（如 `PO-VN-2026-1101`、`INV-VN-PET-150D`），**主故事以 PO-1001 / MO-2001 / MAT-3001 为准**。

---

## 2. 对象清单与属性（登记口径）

以下均可在「管理 → 结构化数据」中按类型查看；领域选 **制造试点**，数据源选 **制造试点 Fixture**。

### 2.1 工厂 `factory`

| 外部编号 | 标题 | 关键 attrs |
| --- | --- | --- |
| `FAC-VN-SZ` | 申洲国际越南工厂 | `country=VN`，`timezone=Asia/Ho_Chi_Minh`，`company=申洲国际` |
| `FAC-NB-SZ` | 申洲国际宁波基地 | `country=CN`，`timezone=Asia/Shanghai` |

### 2.2 产线 `line`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `LINE-01` | 越南一厂成衣一线 | factory / `FAC-VN-SZ` | `shift=A`，`capacity_pcs_per_day=5000`，`team=成衣一组`，status=`running` |
| `LINE-NB-B` | 宁波基地仓储配套线 | factory / `FAC-NB-SZ` | `capacity_pcs_per_day=3000` |

### 2.3 设备 `equipment`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `EQ-4001` | 越南一线圆机 EQ-4001 | line / `LINE-01` | `status=RUNNING`，`waiting_material=true`，`fault_open=false`，`anomaly=等关键面料…`，`model=CIRCULAR-KNIT-X` |

### 2.4 物料 `material`

| 外部编号 | 标题 | 关键 attrs |
| --- | --- | --- |
| `MAT-3001` | 关键针织面料 MAT-3001 | `sku=MAT-3001`，`spec=关键面料`，`uom=kg` |

### 2.5 客户订单 `customer_order`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `PO-1001` | 品牌客户订单 PO-1001 | factory / `FAC-VN-SZ` | `status/order_status=at_risk`，`order_qty=10000`，`due_date≈今天+2天`，`customer_name=全球运动品牌 A`，`product_sku=SZ-TEE-42` |

### 2.6 生产工单 `production_order`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `MO-2001` | 越南生产工单 MO-2001（延期风险） | line / `LINE-01` | `risk_status=at_risk`，`planned_qty=10000`，`completed_qty=6000`，`shortage_qty=1000`，`required_qty=10000`，挂接 `customer_order_external_id` / `material_external_id` / `equipment_external_id` 等 |

### 2.7 库存 `inventory`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `INV-VN-MAT-3001` | 越南仓 MAT-3001 | factory / `FAC-VN-SZ` | `qty=200`，`status=low`，`warehouse_code=VN-WH-01` |
| `INV-NB-MAT-3001` | 宁波仓 MAT-3001 | factory / `FAC-NB-SZ` | `qty=2200`，`status=ok`，`transferable_surplus=2000`，`warehouse_code=NB-WH-02` |

> 界面位置：结构化数据列表按 **对象类型** 筛选；库存不在「物料」页，而在 **inventory / 库存** 类型下，域为「制造试点」、源为「制造试点 Fixture」。

### 2.8 人员 `employee`

| 外部编号 | 标题 | 父级 | 关键 attrs |
| --- | --- | --- | --- |
| `EMP-001` | 生产经理 陈工 | factory / `FAC-VN-SZ` | `employee_no=SZ-VN-PM-001`，`role=production_manager`，`can_request_transfer=true`，`approver_role=warehouse_supervisor` |

---

## 3. 有向关系（依赖怎么连）

在「结构化数据 → 有向关系」可核对；种子写入的边：

| 关系类型 | From → To | 含义 / 属性 |
| --- | --- | --- |
| `belongs_to` | LINE-01 → FAC-VN-SZ；LINE-NB-B → FAC-NB-SZ | 产线归属工厂 |
| `located_in` | EQ-4001 → LINE-01 | 设备位于产线 |
| `located_in` | INV-VN… → FAC-VN-SZ；INV-NB… → FAC-NB-SZ | 库存位于工厂 |
| `belongs_to` | MO-2001 → PO-1001 | 工单归属客户订单（attrs: `erp_po` / `mes_mo`） |
| `work_order_for` | MO-2001 → LINE-01；MO-2001 → EQ-4001 | 工单占用产线/设备 |
| `consumes` | MO-2001 → MAT-3001 | 消耗物料（`required_qty=1000`，`uom=kg`） |
| `consumes` | MO-2001 → INV-VN… | 消耗越南仓（`shortage_qty=1000`） |
| `responsible_for` | EMP-001 → MO-2001；EMP-001 → PO-1001 | 负责人 |

父级列（`parent_object_type` / `parent_external_id`）与上述关系互补，便于按父查询子对象。

---

## 4. 跨系统身份（编号解析）

「管理 → 跨系统身份」或结构化页 **编号解析**：

| 对象类型 | 系统 | 外部编号 | 说明 |
| --- | --- | --- | --- |
| `customer_order` | `erp` / `nb-erp` | `PO-1001` | 同一 Canonical |
| `production_order` | `mes` / `vn-mes` | `MO-2001`；`erp` → `ERP-MO-2001` | 同一 Canonical |
| `material` | `erp` / `nb-erp` | `MAT-3001`；兼容 `RM-PET-150D` | 与 WMS 同 Canonical |
| `material` | `vn-wms` | `YN-MAT-3001`；兼容 `YN-RM-150` | 越南仓料号 |
| `equipment` | `mes` / `vn-mes` | `EQ-4001` | |

**手工解析步骤：**

1. 打开结构化数据页底部「编号解析」。
2. 对象类型选择 `material`（或输入）。
3. 外部编号填 `YN-MAT-3001`（必填；空值会前端提示「请输入外部编号」，不再抛英文原文）。
4. 可选数据源；点击「解析」。
5. 结果应指向与 `MAT-3001` / `RM-PET-150D` 相同的 Canonical。

重复把已占用的 `(system, external_id)` 绑到另一 Canonical 应返回冲突（验收门禁期望 409）。

---

## 5. 手工登记逐步操作（不用种子时）

按依赖顺序录入，避免孤儿引用。权限需具备结构化 / Ontology 管理相关权限（演示用 `alice`）。

### 步骤 A · 建源与域

1. 进入 **管理 → 结构化数据**。
2. **数据源**：新建，名称 `制造试点 Fixture`，类型选 WMS（或自定义），启用；`meta` 可写 `{"seed":true,"domain":"mfg","company":"申洲国际"}`。
3. **业务域**：新建，编码 `mfg`，名称 `制造试点`，类型 generic，启用。

### 步骤 B · 工厂 → 产线 → 设备

1. 对象类型 `factory`，新建 `FAC-VN-SZ`、`FAC-NB-SZ`，attrs 按第 2.1 节。
2. 对象类型 `line`，新建 `LINE-01`（父=越南厂）、`LINE-NB-B`（父=宁波）。
3. 对象类型 `equipment`，新建 `EQ-4001`（父=`LINE-01`），勾上/写入 `waiting_material`、异常说明。

### 步骤 C · 物料 → 库存

1. `material`：`MAT-3001`。
2. `inventory`：越南仓 qty=200、宁波仓 qty=2200，attrs 中写 `material_external_id=MAT-3001`。

### 步骤 D · 订单 → 工单 → 人员

1. `customer_order`：`PO-1001`，`at_risk`，交期近、数量 10000。
2. `production_order`：`MO-2001`，挂客户订单/物料/产线/设备，写入 `shortage_qty`、`risk_status`。
3. `employee`：`EMP-001`，`can_request_transfer=true`。

### 步骤 E · 有向关系

在「有向关系」按第 3 节逐条添加（至少：工单→客户订单、工单→物料、工单→越南库存、人员→工单、设备→产线）。

### 步骤 F · 身份映射

在「跨系统身份」为客户订单 / 工单 / 物料 / 设备创建 Canonical，并附加第 4 节多系统编号。

### 步骤 G · 术语与 SOP（可选但建议）

1. **术语表**：建「针织关键面料-3001」，别名含 ERP/WMS 料号。
2. **知识闭环 / 知识条目**：新建 POLICY「跨厂物料调拨 SOP」，发布；问题与变体覆盖「缺料怎么办」「MO-2001 缺料」等，便于 RAG 与结构化语义对照。

### 步骤 H · 同步按钮说明

「制造试点 Fixture」为种子源，**无真实连接器**。点「同步」应得到友好提示（不可同步），不要当作故障。删除源：在数据源行使用删除（需确认无误）。

---

## 6. 操作与验收（查风险 → 调拨）

### 6.1 结构化查询

1. 列表筛选 `production_order`，应看到 `MO-2001`，`risk_status=at_risk`。
2. 打开对象详情 / 邻居，应看到物料、产线、设备、库存等邻居。
3. 库存类型下核对越南 200 / 宁波 2200。

### 6.2 规则与动作

进入 **管理 → 规则与动作**（或等价入口）：

1. **试运行** `production.query_risk`，参数可带 `risk_status=at_risk` → 至少命中 `MO-2001`。
2. **调拨** `material.transfer`：
   - `source_inventory_id` = 宁波仓记录 ID  
   - `target_inventory_id` = 越南仓记录 ID  
   - `qty` = 例如 `50`  
   - `production_order_id` = MO-2001 ID  
   - `material_external_id` = `MAT-3001`
3. 无审批直接执行 → 状态应为 **待审批**（`awaiting_approval`）。
4. 创建审批并勾选 **acknowledge_risk**（跨厂高风险）后再执行 → **成功**；宁波 qty−50，越南 qty+50；同一 `idempotency_key` 重放不重复扣减。

### 6.3 知识库问答专家（自然语言）

建议提问（应走制造语义支路 / 结构化证据，而非纯闲聊）：

1. 「今天有哪些生产订单可能延期？缺什么料？怎么处理？」→ 应提到 `MO-2001`、缺料、调拨建议。
2. 「RM-PET-150D 和 YN-RM-150 是不是同一物料？」→ 同一 Canonical。
3. 对照：「织机怎么保养？」→ 应走普通 RAG，不进制造风险 Action。

### 6.4 开放平台 / MCP（外部 Agent）

应用需开通 entity / action / mcp 等能力，并授权对应知识库。典型工具链：

1. `describe_ontology`  
2. `query_objects`（`object_type=production_order`，`risk_status=at_risk`）  
3. `get_object` / `traverse`（邻居）  
4. `list_actions` → `production.query_risk` / `material.transfer`  
5. 审批后 `invoke` 调拨，核对结果与审计。

### 6.5 一键验收

```bash
docker compose -f deploy/docker-compose.yml exec backend \
  python -m app.cli ontology accept-mfg --org default --user alice
```

自动门禁覆盖：种子、身份同 Canonical + 重复绑码冲突、查询/遍历、风险查询、调拨审批与幂等、审计。人工清单见命令输出中的 `manual_checklist`。

---

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| 编号解析报「请输入外部编号」 | 外部编号为空；先填再点解析 |
| 列表里看不到库存 | 对象类型选 `inventory`，域选「制造试点」，源选「制造试点 Fixture」 |
| 同步失败 / 提示无连接器 | 种子源预期行为；换真实连接器源再同步 |
| 调拨一直待审批 | 需 `acknowledge_risk` 的审批单，再带 `approval_id` 执行 |
| SOP 搜不到 | 组织下无知识库时种子会跳过 KO；先建 KB 再 `seed-mfg`，并确认索引已消费 |
| 旧编号 vs 新编号 | 主故事用 `PO-1001`/`MO-2001`/`MAT-3001`；旧号为兼容残留 |

---

## 8. 相关代码与文档

| 路径 | 用途 |
| --- | --- |
| `backend/app/services/structured/seed_mfg.py` | 幂等种子 |
| `backend/app/services/ontology_studio/accept_mfg.py` | 闭环验收 |
| `backend/app/services/action/runtime.py` | `production.query_risk` / `material.transfer` |
| `docs/ontology.md` | Ontology 合约与分层 |
| `docs/ops/semantic-center.md` | 语义中心 / 身份 / 规则 |
| `docs/superpowers/specs/2026-11-25-industrial-ontology.md` | 工业级 29 项自检（29/29） |
