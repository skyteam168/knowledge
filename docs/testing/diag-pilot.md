# 设备故障诊断助手试点门禁（O5）

## 种子

```bash
cd backend
python -m app.cli structured seed-equipment --org <ORG_ID>
```

幂等。扩展链路：`SITE-DEMO` → `AREA-WEAVE-A` → `LINE-LOOM-1` → `EQ-LOOM-01`（equipment）→ `CMP-FEED-ROLLER` / `FM-YARN-BREAK`，并挂 `hasPart` / `hasFailureMode` / `causedBy` / `workOrderFor` / `spareFor` 有向边；KO「断纱检修指引」与设备镜像仍由原种子提供。

## 金标（结构门禁）

- 用例：`backend/tests/fixtures/diag_gold.jsonl`（≥20）
- 门禁：`pytest tests/test_diag_gate.py -q`
- 退出码 0 即结构金标通过（现象→根因→工单/备件/本体工具可查）。

> 人审多跳问答（LLM 判分）可在有 MaaS 环境后叠加；本门禁先保证对象图与工具链可打穿。

## 冒烟剧本

1. `describe_ontology` → 含 `hasFailureMode`
2. `query_objects` `device` q=飞织 → `EQ-LOOM-01`
3. `get_object` equipment/`EQ-LOOM-01` → 邻居含断纱故障模式
4. `traverse` out `has_failure_mode|caused_by|has_part` → 故障/部件
5. `get_object` failure_mode → `FM-YARN-BREAK`

自动化：`test_diag_smoke_tool_script`。

## GATE-1 核对

| 项 | 状态 |
| --- | --- |
| 试点产线建模（演示工厂/车间/产线/设备） | 种子已覆盖 |
| 设备→工单→备件可查（get/query/traverse） | 种子边 + 门禁 |
| O1–O5 pytest | `test_diag_gate` + 各阶段单测 |
| 诊断金标门禁 | `test_diag_gate` / `diag_gold.jsonl` |
