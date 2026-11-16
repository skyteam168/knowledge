# 暴露面检查清单（单机 / 内网）

> 上线或开放外网前逐项勾选。开发 `docker-compose.yml` 为便利默认绑定宿主机端口；**生产勿把数据面端口直接对公网**。

---

## 1. 原则

| 层级 | 应对公网 | 说明 |
| --- | --- | --- |
| TLS 边缘 / frontend(nginx) | 可 | 浏览器入口 |
| Keycloak（经 TLS 或反代） | 可（OIDC） | 勿裸奔管理控制台到公网 |
| backend:8000 | **否** | 仅经 nginx `/api`；生产 compose 通常不映射 |
| postgres / redis / minio / qdrant / opensearch | **否** | 仅 Docker 网络；宿主机绑定建议 `127.0.0.1:` |

---

## 2. 开发栈（`deploy/docker-compose.yml`）默认映射

| 服务 | 默认端口 | 风险 | 建议 |
| --- | --- | --- | --- |
| postgres | `5432` | 弱口令时局域网可连 | 改为 `"127.0.0.1:5432:5432"` 或去掉端口 |
| redis | （见 compose） | 无密码 | 仅本机或加密码 |
| minio | `9000` | API/控制台 | `127.0.0.1:9000`；生产用独立凭据 |
| qdrant | `6333` | 无认证（开发） | `127.0.0.1:6333`；生产设 `QDRANT_API_KEY` |
| opensearch | `9200` | **无安全插件**（`DISABLE_SECURITY_PLUGIN`） | **禁止对公网**；仅容器网 + 本机调试 |
| keycloak | `8080` / `8180` | 管理入口 | 生产经 TLS；改默认 admin 密码 |
| backend | `8000` | 完整 API | 生产不映射；开发仅本机 |
| frontend | `3000` | SPA | 可对内网 |

勾选（部署前）：

- [ ] 数据面端口未映射到 `0.0.0.0`（或仅 `127.0.0.1`）  
- [ ] OpenSearch 未对非受信网络开放  
- [ ] MinIO root 非默认口令（生产）  
- [ ] Keycloak admin / realm 密钥已轮换  
- [ ] `OPEN_API_*` pepper、directory secret 非示例值  

---

## 3. OpenSearch 安全

当前开发/多数单机 profile：**关闭** OpenSearch Security 插件，HTTP 明文、无 RBAC。

- [ ] 已确认仅内网/本机可达  
- [ ] 生产若必须暴露：启用官方 Security 插件或前置 mTLS 反代（本仓库默认不做）  
- [ ] 快照目录 `path.repo` 权限仅给 OS 进程  

---

## 4. MinIO

- [ ] `MINIO_ROOT_USER` / `PASSWORD` 非 `minioadmin`  
- [ ] 桶策略非 public；预签名由 backend 签发  
- [ ] 控制台端口未对公网（若启用）  

---

## 5. 应用层补强（已有能力复核）

- [ ] Open API：IP 白名单 + Key 吊销抽检  
- [ ] 限流：`RATE_LIMIT_*` 按环境调过  
- [ ] 审计：抽查写操作有 `audit` 记录  
- [ ] 备份目录与数据盘分离 / 异地（见 backup 演练）  

---

## 6. 快速自检命令（本机）

```bash
# 从另一台机器应失败（若已绑 127.0.0.1）；本机可通
curl -sS -m 2 http://127.0.0.1:9200 || echo "opensearch closed/unreachable"
curl -sS -m 2 http://127.0.0.1:9000/minio/health/live || echo "minio closed"
```

生产服务器上应用 `ss -lntp` / 安全组核对：仅 443（及必要的 Keycloak）对外开放。
