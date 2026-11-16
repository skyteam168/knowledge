# 结构化镜像连接器（CSV / REST）

阶段 1：把 ERP/MES 设备域数据定时或手动拉取进 PostgreSQL `equip_*` 本地镜像。不做 Ontop / SPARQL。

## 配置

在管理端「结构化数据」新建源（类型建议 `mes` / `erp`），或直接写 `structured_sources.meta`：

### CSV

```json
{
  "connector": "csv",
  "sync_interval_minutes": 60,
  "csv": {
    "devices": "/data/mes/devices.csv",
    "work_orders": "/data/mes/work_orders.csv",
    "spare_parts": "/data/mes/spare_parts.csv"
  }
}
```

样例文件：`backend/fixtures/structured/*.csv`（列名 `external_id,name,...`）。可用 `column_map` 映射自定义表头。

### REST

```json
{
  "connector": "rest",
  "sync_interval_minutes": 30,
  "rest": {
    "base_url": "https://mes.example/api/",
    "bearer_env": "MES_API_TOKEN",
    "paths": {
      "devices": "/v1/devices",
      "work_orders": "/v1/work-orders",
      "spare_parts": "/v1/spare-parts"
    }
  }
}
```

响应可为 JSON 数组或 `{ "items": [...] }`。设备字段识别 `external_id` / `id` / `device_code` 与 `name`。

`sync_interval_minutes = 0`（默认）表示仅手动同步；`> 0` 时由 scheduler 周期检查并入队 worker。

## 同步入口

```bash
# CLI（推荐验收）
cd backend
python -m app.cli structured sync --org default --source-id <SOURCE_ID>
python -m app.cli structured sync --org default --source "MES CSV 连接器" --dry-run

# Admin API
POST /api/admin/structured/sources/{source_id}/sync?dry_run=false
```

管理页：在设备域工具栏选择数据源后点「同步数据源」。

同步成功后 `meta` 写入 `last_sync_at` / `last_sync_status` / `last_sync_stats`；失败写 `last_sync_error`。

## 定时

- 配置：`STRUCTURED_SYNC_CHECK_INTERVAL_SECONDS`（默认 60）
- `scheduler` → `dispatch_structured_syncs` → `sync_structured_source`（Dramatiq 队列 `structured`）

## 验收清单

1. 创建启用源并填好 `meta.connector`
2. 跑一次 CLI 或 API sync，`equip_devices` 出现行
3. `GET /api/admin/structured/resolve?object_type=device&external_id=...` 可解析
4. 再跑一次 sync，`created=0`、多为 `unchanged`
