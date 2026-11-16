# PII 脱敏与 ClamAV 病毒扫描

> 对照：`app/core/config.py`、`services/security/pii.py`、`services/security/file_guard.py`  
> Compose：`deploy/docker-compose.prod.yml`（`--profile clamav`）  
> 环境样例：`deploy/.env.prod.example`、`deploy/.env.example`、`backend/.env.example`

两项均为**可选增强**，代码默认关闭，避免本地开发被扫描器就绪时间或打码误伤打断。生产是否打开取决于上传面与合规要求。

---

## 1. 默认值与生产建议

| 变量 | 代码默认 | 本地开发 | 单机企业生产建议 |
| --- | --- | --- | --- |
| `VIRUS_SCAN_BACKEND` | `none` | 保持 `none` | 允许用户上传时改为 `clamav`，并起 profile |
| `CLAMAV_HOST` / `CLAMAV_PORT` | `localhost` / `3310` | 本机联调可用 | Compose 内用服务名 `clamav`（已写入 prod compose） |
| `PII_MASK_ON_INGEST` | `false` | 通常关 | **慎开**：会改写入库 chunk，已入库内容需重新处理才脱敏 |
| `PII_MASK_ON_OUTPUT` | `false` | 可按需开试 | **建议开**：搜索片段 / 问答 / Open API 输出打码，不改 PG 原文 |
| `PII_TYPES` | `["phone","id_card","bank_card"]` | 可加 `email` | JSON 数组；按合规清单选；未知类型启动失败 |

原则：

1. **ClamAV**：有外网/不可信上传面 → 开；仅管理员受控导入且上游已扫 → 可保持关。  
2. **输出脱敏**：面向员工检索与开放平台时优先开，成本低、可随时关。  
3. **入库脱敏**：仅在明确要求「索引里也不留明文 PII」时开；开启后对新文档生效，旧文档用批量 reprocess / 重建索引补齐。

---

## 2. 行为说明

### 2.1 ClamAV

- 上传经 `FileGuard`：`VIRUS_SCAN_BACKEND=clamav` 时对文件字节走 clamd `INSTREAM`。  
- 检出病毒 → 拒绝上传；扫描器不可达 → `VIRUS_SCAN_UNAVAILABLE`（不静默放行）。  
- Profile 服务**不对外暴露端口**，仅 Docker 网络内 `backend` → `clamav:3310`。

### 2.2 PII

支持类型：`phone`、`id_card`（校验位）、`bank_card`（Luhn）、`email`。

| 开关 | 作用点 |
| --- | --- |
| `PII_MASK_ON_INGEST` | worker 切块入库前遮罩 chunk 文本（随后进 PG / 索引） |
| `PII_MASK_ON_OUTPUT` | 站内搜索、问答材料、Open API `content` 等出站文本 |

---

## 3. 本地可开样例

### 3.1 仅输出脱敏（最快验证）

`deploy/.env` 或 `backend/.env`：

```bash
PII_MASK_ON_OUTPUT=true
PII_TYPES=["phone","id_card","bank_card","email"]
PII_MASK_ON_INGEST=false
VIRUS_SCAN_BACKEND=none
```

重启 backend 后，搜索/问答中含手机号等片段应出现 `*` 遮罩。单测参考 `backend/tests/test_security.py`。

### 3.2 生产 Compose：ClamAV + 输出脱敏

`deploy/.env.prod`（自 `.env.prod.example` 复制后改）：

```bash
VIRUS_SCAN_BACKEND=clamav
CLAMAV_HOST=clamav
# CLAMAV_PORT=3310
PII_MASK_ON_INGEST=false
PII_MASK_ON_OUTPUT=true
PII_TYPES=["phone","id_card","bank_card","email"]
```

```bash
cd deploy
# 写入 metrics-token 等与日常部署相同
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile clamav up -d
# 首次拉病毒库约数分钟；healthy 后再测上传
```

健康：`docker compose … ps clamav` 为 healthy；上传 EICAR 或已知样本应被拒（勿在生产库用真实恶意样本）。

### 3.3 开发机直连本机 clamd（可选）

若宿主机已跑 clamd 并监听 `3310`：

```bash
VIRUS_SCAN_BACKEND=clamav
CLAMAV_HOST=127.0.0.1
CLAMAV_PORT=3310
```

---

## 4. 运维注意

- **扫描器宕机**：开 ClamAV 后上传依赖 clamd；应用侧会报不可用而非跳过。部署/滚动时先保证 clamav healthy。  
- **入库后改开关**：只改 `PII_MASK_ON_OUTPUT` 立即影响出站；改 `PII_MASK_ON_INGEST` 不影响已有 chunk，需文档重新处理。  
- **单机 server compose**（`docker-compose.prod.server.yml`）：默认未捆绑 clamav 服务；要用扫描需自备 clamd 并设 `CLAMAV_HOST`，或改用带 profile 的 `docker-compose.prod.yml`。  
- **资源**：ClamAV 镜像与病毒库体积较大，首次 `start_period` 最长约 5 分钟。

---

## 5. 验收清单（D5）

| 项 | 状态 |
| --- | --- |
| 默认关/开建议写明 | 本文 §1 |
| 本地可开配置样例 | 本文 §3 |
| `.env*.example` 注释 | `deploy/.env.prod.example`、`.env.prod.server.example`、`.env.example`；`backend/.env.example` |
| `deployment.md` §6 链到本文 | 已链 |
