# 接口说明

完整 OpenAPI 文档：启动后端后访问 `http://localhost:8000/docs`。

## 约定

- 业务接口前缀：`/api/v1`
- 请求/响应头 `X-Trace-ID`：可由客户端传入（`[A-Za-z0-9-_.]{1,128}`），否则服务端生成。
- 错误响应：

```json
{ "code": "NOT_FOUND", "message": "Resource not found", "detail": null, "trace_id": "..." }
```

- 分页响应：`{ "items": [], "total": 0, "page": 1, "size": 20 }`

## 阶段 0 接口

### `GET /health`

存活检查，不访问外部依赖。

```json
{ "status": "ok", "app": "Enterprise Knowledge Base", "env": "dev" }
```

### `GET /ready`

就绪检查。必需依赖全部可用返回 200；任一必需依赖不可用返回 503。

```json
{
  "status": "ready | degraded | not_ready",
  "checks": {
    "postgres": { "status": "up", "required": true, "latency_ms": 2.1, "error": null },
    "embedding": { "status": "down", "required": false, "latency_ms": 3000.0, "error": "timeout after 3.0s" }
  }
}
```

依赖项：`postgres`、`redis`、`minio`、`qdrant`、`opensearch`、`keycloak`（必需），
`embedding`、`rerank`、`chat`（可选）。
