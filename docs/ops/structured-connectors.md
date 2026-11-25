# 结构化镜像连接器

把 ERP/MES 设备域数据定时或手动拉取进 PostgreSQL `equip_*` 本地镜像。不做 Ontop / SPARQL。

支持引擎：**MySQL**、**PostgreSQL**、**SQL Server**、**MongoDB**、**CSV**、**REST**。

## 配置（管理端）

「管理 → 结构化数据 → 新建数据源」可选连接器并填表单；密码只写**环境变量名**（如 `MES_MYSQL_PASSWORD`），勿写入 `meta` / git。也可直接写 `structured_sources.meta`：

### MySQL

```bash
export MES_MYSQL_PASSWORD='***'
```

```json
{
  "connector": "mysql",
  "sync_interval_minutes": 60,
  "incremental": { "enabled": true, "field": "create_time" },
  "mysql": {
    "host": "10.10.130.199",
    "port": 3306,
    "database": "maintaince",
    "user": "knowledge",
    "password_env": "MES_MYSQL_PASSWORD",
    "table": "device_info"
  },
  "column_map": {
    "devices": {
      "external_id": "id",
      "name": "device_name",
      "status": "status",
      "location": "device_location",
      "updated_at": "create_time"
    }
  }
}
```

管理 API 探测：`POST /api/v1/admin/structured/mysql/list-tables`、`/mysql/probe`（密码经 env 或一次性字段）。

未配置 `column_map` 时会尝试常见列名（`device_number` / `device_name` / `create_time` 等）。MySQL 账号须授权当前应用主机访问。

### PostgreSQL

```bash
export MES_PG_PASSWORD='***'
```

```json
{
  "connector": "postgres",
  "sync_interval_minutes": 60,
  "postgres": {
    "host": "pg.example",
    "port": 5432,
    "database": "mes",
    "user": "reader",
    "password_env": "MES_PG_PASSWORD",
    "schema": "public",
    "table": "device_info"
  }
}
```

探测：`POST /api/v1/admin/structured/postgres/list-tables`、`/postgres/probe`。

### SQL Server

```bash
export MES_MSSQL_PASSWORD='***'
```

```json
{
  "connector": "mssql",
  "sync_interval_minutes": 60,
  "mssql": {
    "host": "sql.example",
    "port": 1433,
    "database": "mes",
    "user": "reader",
    "password_env": "MES_MSSQL_PASSWORD",
    "schema": "dbo",
    "table": "device_info"
  }
}
```

探测：`POST /api/v1/admin/structured/mssql/list-tables`、`/mssql/probe`。默认 Schema 为 `dbo`。

### MongoDB

```bash
export MES_MONGO_PASSWORD='***'   # 有认证时
```

```json
{
  "connector": "mongo",
  "sync_interval_minutes": 60,
  "mongo": {
    "host": "mongo.example",
    "port": 27017,
    "database": "mes",
    "user": "",
    "password_env": "MES_MONGO_PASSWORD",
    "auth_source": "admin",
    "collection": "devices"
  }
}
```

`user` 可留空（无认证）。探测：`POST /api/v1/admin/structured/mongo/list-collections`、`/mongo/probe`（字段由样本文档推断；`_id` 视作主键）。

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

## Ontology Studio 读库导入

「管理 → Ontology Studio → 连接数据库」可对同一批引擎做只读探测并导入语义草稿（表/列 → 实体/属性）。可复用已有结构化数据源，也可临时填写连接信息。流程与应用内使用说明「Ontology Studio」章节一致。

## 同步入口

```bash
# CLI（推荐验收）
cd backend
python -m app.cli structured sync --org default --source-id <SOURCE_ID>
python -m app.cli structured sync --org default --source "MES CSV 连接器" --dry-run

# Admin API
POST /api/v1/admin/structured/sources/{source_id}/sync?dry_run=false
```

管理页：在设备域工具栏选择数据源后点「同步数据源」。

同步成功后 `meta` 写入 `last_sync_at` / `last_sync_status` / `last_sync_stats`；失败写 `last_sync_error`。

## 定时

- 配置：`STRUCTURED_SYNC_CHECK_INTERVAL_SECONDS`（默认 60）
- `scheduler` → `dispatch_structured_syncs` → `sync_structured_source`（Dramatiq 队列 `structured`）

## 验收清单

1. 创建启用源并填好 `meta.connector`（或管理端表单）
2. 跑一次 CLI 或 API sync，`equip_devices` 出现行
3. `GET /api/v1/admin/structured/resolve?object_type=device&external_id=...` 可解析
4. 再跑一次 sync，`created=0`、多为 `unchanged`

## 属性 schema（O1.2）

工业对象类型（`site`…`event` 等）写入 `structured_records.attrs` 时走类型化校验；数量必须 `{value,unit}`。  
契约与 JSON Schema：`GET /api/v1/admin/structured/attribute-schemas`。详见 [`docs/ontology.md`](../ontology.md)「类型化属性 schema」。
