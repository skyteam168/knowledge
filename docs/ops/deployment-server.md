# 单机部署（复用宿主机 PostgreSQL / Redis + 自签 HTTPS）

适用于：服务器上已经运行 PostgreSQL 16 和 Redis，只用 Docker 跑知识库其余组件；局域网 IP 访问，使用自签证书。

文件：`deploy/docker-compose.prod.server.yml`、`deploy/.env.prod.server.example`、`deploy/nginx/tls-gateway.conf`、`deploy/keycloak/realm-ekb.prod.json`。

参考实例：`10.10.130.170`（Rocky Linux + 宝塔），代码目录 `/www/wwwroot/flyknit-knowledge`。

## 1. 拓扑与端口

```
浏览器 ──https:8443──► tls-gateway ──► frontend:8080 ──► backend:8000
       ──https:8444──► tls-gateway ──► keycloak:8080   （登录页 + 管理后台）
       ──https:9443──► tls-gateway ──► minio:9000      （预签名上传 / 预览）
容器 ──► 宿主机 PostgreSQL:5432（ekb、keycloak 两个库）、Redis:6379
```

| 宿主机端口 | 用途 | 变量 |
|---|---|---|
| 8443 | 知识库（HTTPS） | `TLS_HTTPS_PORT` |
| 8444 | Keycloak（HTTPS） | `TLS_KEYCLOAK_PORT` |
| 9443 | MinIO（HTTPS） | `TLS_MINIO_PORT` |
| 8088 / 8090 / 9000 | 对应的 HTTP 端口，仅排障用 | `HTTP_PORT` / `KEYCLOAK_HOST_PORT` / `MINIO_HOST_PORT` |

- 必须走 HTTPS：浏览器在 `http://<IP>` 上禁用 Web Crypto，Keycloak 的 PKCE 登录会直接失败（控制台报 `Web Crypto API is not available`）。
- 打开知识库后跳转到 8444 是正常的：登录页由 Keycloak 提供（套用 ekb 主题），登录成功后自动回到 8443。
- 避开面板占用的 443；8080/8081/8082 在共享主机上常被占用，所以 Keycloak 的 HTTP 端口用 8090。部署前确认端口空闲：

```bash
ss -lntp | grep -E ':(8088|8090|9000|8443|8444|9443)\b'
```

## 2. 前置条件

### 2.1 Docker

Docker 20.10+ 与 Compose v2（`docker compose version`）。

### 2.2 PostgreSQL

宿主机没有 `psql` 时，用容器内的客户端（`--network host` 走本机）：

```bash
PSQL="docker run --rm -i --network host -e PGPASSWORD=<PG密码> postgres:16-alpine psql -h 127.0.0.1 -U postgres"
$PSQL -c "CREATE DATABASE ekb OWNER postgres;"
$PSQL -c "CREATE DATABASE keycloak OWNER postgres;"
```

容器访问宿主机 PG 时，来源 IP 是 Docker 网段（compose 自定义网段如 `172.25.0.x`，不一定是 `172.17`）。在 `pg_hba.conf` 末尾加一行后重载，否则 migrate / keycloak 报 `no pg_hba.conf entry`：

```bash
find / -name pg_hba.conf 2>/dev/null          # 找到配置文件，先备份
# 追加：
# host    all    all    172.16.0.0/12    md5
$PSQL -c "SELECT pg_reload_conf();"
```

同时确认 `postgresql.conf` 的 `listen_addresses` 包含宿主机 IP（或 `*`）。

### 2.3 Redis

- 需要能从 Docker 网段访问（`bind` 包含宿主机 IP，`protected-mode` 配合密码）。
- 密码里的特殊字符要做 URL 编码后写入 `REDIS_PASSWORD`，例如 `redis@2026` 写成 `redis%402026`（`@`→`%40`，`:`→`%3A`，`/`→`%2F`，`#`→`%23`）。
- 用独立的 `REDIS_DB`（如 1），避免和宿主机其他应用冲突。

### 2.4 防火墙

```bash
firewall-cmd --permanent --add-port={8443,8444,9443}/tcp && firewall-cmd --reload
```

## 3. 首次部署

### 3.1 代码

```bash
cd /www/wwwroot
git clone https://github.com/skyteam168/knowledge.git flyknit-knowledge
cd flyknit-knowledge/deploy
```

### 3.2 环境变量

`.env.prod.server` 含密钥，已加入 `.gitignore`，不会随 git 同步。新服务器上从模板复制后填写，或从旧服务器 / 本机 `scp` 过去：

```bash
cp .env.prod.server.example .env.prod.server
openssl rand -hex 24      # 生成各类密钥，每个变量单独生成一次
```

必须按服务器修改的项：

| 变量 | 示例 |
|---|---|
| `PUBLIC_URL` | `https://10.10.130.170:8443` |
| `KEYCLOAK_PUBLIC_URL` | `https://10.10.130.170:8444` |
| `MINIO_PUBLIC_ENDPOINT` | `https://10.10.130.170:9443` |
| `POSTGRES_HOST` / `POSTGRES_PASSWORD` | 宿主机 IP / PG 密码 |
| `REDIS_HOST` / `REDIS_PASSWORD` / `REDIS_DB` | 宿主机 IP / URL 编码后的密码 / 1 |
| `SSL_CERT_DIR` | 证书目录，默认 `./certs` |
| 模型相关 `EMBEDDING_*` / `RERANK_*` / `CHAT_*` / `LLM_API_KEY` | 按模型服务填写 |

需要随机生成的密钥：`MINIO_ROOT_PASSWORD`、`QDRANT_API_KEY`、`KEYCLOAK_ADMIN_PASSWORD`、`OPEN_API_KEY_PEPPER`、`DIRECTORY_SECRET_KEY`、`OIDC_BRIDGE_SIGNING_KEY`、`OIDC_BRIDGE_CLIENT_SECRET`、`KEYCLOAK_ADMIN_CLIENT_SECRET`、`METRICS_TOKEN`。

### 3.3 证书

把证书放到 `SSL_CERT_DIR`，文件名固定为 `cert.pem` 和 `key.pem`（`*.pem` 已加入 `.gitignore`）：

```bash
mkdir -p certs
cp /path/to/cert.pem /path/to/key.pem certs/
```

没有证书时可现场生成一张包含 IP 的自签证书：

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=10.10.130.170" -addext "subjectAltName=IP:10.10.130.170"
```

### 3.4 启动

```bash
DC="docker compose -f docker-compose.prod.server.yml --env-file .env.prod.server"
$DC up -d --build --wait
$DC ps
```

启动顺序由健康检查保证：minio / qdrant / opensearch → keycloak（首次导入 `realm-ekb.prod.json`）→ migrate → backend → keycloak-setup（成功后退出）→ worker / outbox-dispatcher / scheduler → frontend → tls-gateway。outbox-dispatcher 启动时会自动创建活动索引代；也可以手动执行 `$DC exec backend python -m app.cli index bootstrap`（幂等）。

`ekb/*` 镜像只在本地构建（`pull_policy: build/never`），不要 `docker pull`。

### 3.5 验证

```bash
curl -sk -o /dev/null -w "app %{http_code}\n" https://127.0.0.1:8443/
curl -sk https://127.0.0.1:8444/realms/ekb/.well-known/openid-configuration | grep -o '"issuer":"[^"]*"'
curl -sk -o /dev/null -w "minio %{http_code}\n" https://127.0.0.1:9443/minio/health/live
$DC exec frontend sh -c 'grep -rl "10.10.130.170:8444" /usr/share/nginx/html/assets | head -1'
```

期望：`app 200`；`issuer` 为 `https://<IP>:8444/realms/ekb`；`minio 200`；最后一条能输出一个 js 文件名（前端打包进了正确的 Keycloak 地址）。

## 4. Keycloak 配置

以下命令都在 `deploy` 目录执行，每条独立一行，避免多行粘贴时丢失收尾引号（终端出现 `>` 提示符即表示引号未闭合，补一个 `'` 回车或 Ctrl+C）。

```bash
DC="docker compose -f docker-compose.prod.server.yml --env-file .env.prod.server"
K=/opt/keycloak/bin/kcadm.sh
# 登录 kcadm：管理员账号取容器内的 KC_BOOTSTRAP_ADMIN_*，宿主机 shell 里没有 $KEYCLOAK_ADMIN
$DC exec -T keycloak bash -c "$K config credentials --server http://127.0.0.1:8080 --realm master --user \$KC_BOOTSTRAP_ADMIN_USERNAME --password \$KC_BOOTSTRAP_ADMIN_PASSWORD"
```

成功输出 `Logging into http://127.0.0.1:8080 as user admin of realm master`。若报 `invalid_grant`，说明 admin 密码已不是 `.env` 中的值（`KEYCLOAK_ADMIN_PASSWORD` 只在 Keycloak 首次启动时生效）。

### 4.1 更新前端回调地址

realm 只在首次启动时导入。之后修改 `PUBLIC_URL`（换 IP、HTTP 改 HTTPS、换端口）必须手动更新 `ekb-frontend` 客户端：

```bash
URL=https://10.10.130.170:8443
CID=$($DC exec -T keycloak $K get clients -r ekb -q clientId=ekb-frontend --fields id --format csv --noquotes | tail -1 | tr -d '\r')
$DC exec -T keycloak $K update clients/$CID -r ekb -s rootUrl=$URL -s "redirectUris=[\"$URL/*\"]" -s "webOrigins=[\"$URL\"]" -s "attributes.\"post.logout.redirect.uris\"=$URL/*"
$DC exec -T keycloak $K get clients/$CID -r ekb --fields rootUrl,redirectUris,webOrigins
```

### 4.2 创建知识库管理员

生产 realm 不带任何可登录用户（`alice` / `bob` / `carol` 只在开发 realm）。密码策略：至少 12 位，且含大写、小写、数字，不能与用户名相同，不能与最近 5 次相同。

```bash
U=admin
$DC exec -T keycloak $K create users -r ekb -s username=$U -s enabled=true -s email=admin@example.com -s emailVerified=true -s firstName=系统 -s lastName=管理员
$DC exec -T keycloak $K set-password -r ekb --username $U --new-password 'Abcdef.12345'
UID_=$($DC exec -T keycloak $K get users -r ekb -q username=$U --fields id --format csv --noquotes | tail -1 | tr -d '\r')
$DC exec -T keycloak $K update users/$UID_ -r ekb -s 'attributes.org_id=["default"]'
$DC exec -T keycloak $K add-roles -r ekb --uusername $U --rolename kb_admin --rolename platform_admin
$DC exec -T keycloak $K get users/$UID_ -r ekb --fields username,enabled,attributes
```

- `set-password` 成功时无输出；报 `invalidPasswordMin...Message` 表示不符合密码策略，此时账号没有密码，登录一定提示“无效的用户名或密码”。
- 最后一条应能看到 `"org_id" : [ "default" ]`。缺省时后端也会归到 `default` 组织。
- 角色：`kb_admin` 全部权限；`kb_editor` 编辑；`kb_viewer` 只读（新用户首次登录无角色时默认）；`platform_admin` 跨组织，不需要可去掉。
- 也可在 `https://<IP>:8444/admin` → 切换到 ekb realm → Users 中手动创建，Attributes 里加 `org_id = default`。

### 4.3 解除登录锁定

realm 开启了防暴力破解，连续输错 5 次会临时锁定：

```bash
$DC exec -T keycloak $K delete attack-detection/brute-force/users/$UID_ -r ekb
```

查看登录失败原因：

```bash
$DC logs --tail=100 keycloak | grep -E "LOGIN_ERROR|error="
```

| `error=` | 含义 |
|---|---|
| `user_not_found` | 用户不存在（检查是否建在 ekb realm） |
| `invalid_user_credentials` | 密码错误或未设置成功 |
| `user_temporarily_disabled` | 被锁定，按上面解除 |

## 5. 浏览器首次访问

自签证书需要每个端口单独信任一次（页面内的跨端口请求被拦截时不会弹提示，只会静默失败）：

1. `https://<IP>:8444` → 高级 → 继续访问
2. `https://<IP>:9443/minio/health/live` → 继续访问（否则上传、预览图片失败）
3. `https://<IP>:8443` → 登录

想彻底去掉警告：把 `cert.pem` 导入客户端的“受信任的根证书颁发机构”，或换成内网 CA 签发的证书（SAN 必须包含访问用的 IP / 域名）。

## 6. 更新升级

```bash
cd /www/wwwroot/flyknit-knowledge && git pull && cd deploy
diff <(grep -o '^[A-Z_]*=' .env.prod.server.example | sort) <(grep -o '^[A-Z_]*=' .env.prod.server | sort)   # 检查是否有新增变量
DC="docker compose -f docker-compose.prod.server.yml --env-file .env.prod.server"
$DC up -d --build --wait
```

- 升级前先按 [备份与恢复](backup-restore.md) 备份 PG。
- compose 新增服务后报 `no such service: xxx`，说明服务器上的 compose 文件不是最新的，先 `git pull`。
- 修改 `KEYCLOAK_PUBLIC_URL` 后必须重建前端（地址在构建时写入）：`$DC up -d --build frontend`。
- 修改 `PUBLIC_URL` 后按 4.1 更新 Keycloak 客户端。
- 只改 `tls-gateway.conf` 或更换证书：`$DC restart tls-gateway`。

## 7. 迁移到新服务器

1. 按第 2 节准备 PG（建库、`pg_hba`）、Redis、端口、防火墙。
2. 克隆代码，复制旧服务器的 `.env.prod.server`，把其中的 IP 全部替换：

   ```bash
   sed -i 's/10\.10\.130\.170/<新IP>/g' .env.prod.server
   ```

3. 放置证书（新 IP 需要新证书，SAN 要包含新 IP）。
4. 如需保留数据，按 [备份与恢复](backup-restore.md) 恢复 `ekb`、`keycloak` 两个库和 MinIO；Qdrant / OpenSearch 是派生索引，恢复后按 [索引重建](reindex.md) 从 PG + MinIO 重建。
5. `$DC up -d --build --wait`，按 3.5 验证。
6. 恢复了 keycloak 库时按 4.1 把回调地址改成新 IP；全新 keycloak 库则按 4.2 创建管理员。

## 8. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `pull access denied for ekb/backend` | 本地构建的镜像，不能从 Docker Hub 拉；用 `up -d --build`，不要单独 `pull` |
| `bind: address already in use` | 端口被占用，修改 `.env` 中对应端口变量 |
| `no pg_hba.conf entry for host "172.x.x.x"` | 按 2.2 放行 `172.16.0.0/12` 并 `pg_reload_conf()` |
| Redis 认证失败 / URL 解析错误 | 密码特殊字符未 URL 编码 |
| 登录页报 `Web Crypto API is not available` | 用了 HTTP 访问，改用 `https://<IP>:8443` |
| `no such service: tls-gateway` | 服务器上 compose 文件不是最新，`git pull` |
| `curl` HTTPS 返回 `000` | tls-gateway 未启动或证书缺失，看 `$DC logs tls-gateway`（`cannot load certificate`） |
| 登录后报 `Invalid redirect uri` | `ekb-frontend` 回调地址未更新，按 4.1 |
| kcadm `as user  of realm master` + `invalid_grant` | 宿主机 shell 里没有 `$KEYCLOAK_ADMIN`，改用容器内 `KC_BOOTSTRAP_ADMIN_*`（第 4 节） |
| 终端停在 `>` 提示符 | 多行命令引号未闭合，补 `'` 回车或 Ctrl+C 后用单行命令 |
| “无效的用户名或密码” | 密码不符合策略未设置成功、用户名不对，或已被锁定；按 4.2 / 4.3 排查 |
| 上传文件 / 图片预览失败 | 浏览器未信任 9443 端口证书，或 `MINIO_PUBLIC_ENDPOINT` 与访问地址不一致 |
