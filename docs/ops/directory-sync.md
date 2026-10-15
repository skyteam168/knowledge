# 组织架构同步与扫码登录

从企业微信、钉钉、泛微 e-cology 9 或 Excel 同步部门、人员、多部门归属与职务，并支持企业微信 / 钉钉扫码登录。
入口：「管理 → 组织同步」，需要 `admin:directory` 权限（系统管理员默认具备）。

## 1. 基本规则

- 每个组织最多一个**主数据源**：它管理部门树、人员、主部门、兼职部门和职务。
  其他数据源只绑定身份（用于扫码登录识别），按「工号 > 手机 > 邮箱 > 账号」匹配已有用户。
- 同步**不删除**用户，只停用；上游删除的部门标记为「已归档」，不再出现在选择框，原有授权记录保留并继续生效。
- 先「预览差异」再「应用」。预览不写库。单次停用人数超过在职人数的 `DIRECTORY_SYNC_MAX_DISABLE_RATIO`
  （默认 20%，且至少 5 人）时同步中止，需要在预览页确认后「强制应用」。
- 主数据源管理的字段在后台只读：部门名称与上级、用户账号 / 姓名 / 工号 / 邮箱 / 手机 / 职务 / 部门。
  角色、本地用户组、启用状态仍可在后台修改。删除数据源后，这些记录转为本地记录，可以再次编辑。
- 职务同步为用户组「职务/<职务名>」，可以直接用于知识库授权。
- 部门在授权选择框、用户列表、ACL 列表中显示完整路径，如「集团 / 越南Flyknit / 织造车间」，可按路径搜索。
- 同步应用后权限缓存立即失效，下一次请求按新架构计算权限。
- 自动同步：数据源设置「同步间隔（分钟）」后由 scheduler 每分钟检查并派发；留空表示仅手动。

## 2. 企业微信

### 2.1 通讯录同步（必需）

1. 管理后台 →「我的企业 → 企业信息」：记下**企业 ID（CorpID）**。
2. 「安全与管理 → 管理工具 → 通讯录同步」：开启 API 接口同步，查看 **Secret**（通讯录同步 Secret，权限选「只读」即可）。
3. 「企业可信 IP」：把后端服务器的**出口公网 IP** 加入（否则接口返回 60020）。
4. 如果工号保存在成员自定义字段里，在数据源配置「工号字段名」中填写该字段名（默认「工号」）。

企业微信对新应用收紧了手机、邮箱等字段，拿不到的字段同步为空，不影响部门与人员同步。

### 2.2 扫码登录（可选）

1. 「应用管理 → 自建」创建应用（如「知识库」），记下 **AgentId** 和 **Secret**，可见范围设为需要登录的人员。
2. 应用详情 →「企业微信授权登录」：授权回调域填写前端域名（与 `PUBLIC_BASE_URL` 的域名一致）。
3. 应用详情 →「网页授权及 JS-SDK」：可信域名填写同一域名（企业微信内打开免扫码登录需要）。
4. 在数据源配置中填写「扫码登录应用 AgentId / Secret」，保存后数据源列表显示「扫码登录已配置」。

回调地址固定为 `{PUBLIC_BASE_URL}/oidc/wecom/callback`。

## 3. 钉钉

1. 钉钉开发者后台创建企业内部应用，记下 **AppKey（Client ID）** 和 **AppSecret（Client Secret）**。
2. 「权限管理」开通：通讯录部门信息读权限、成员信息读权限、通讯录个人信息读权限（扫码登录获取 unionId 用）。
   缺少权限时接口返回 60011。
3. 如果应用开启了服务器出口 IP 白名单，加入后端出口 IP（否则返回 60020）。
4. 扫码登录：「安全设置 → 重定向 URL」填写 `{PUBLIC_BASE_URL}/oidc/dingtalk/callback`。
   钉钉扫码登录复用同一组 AppKey / AppSecret，不需要额外配置。

## 4. 泛微 e-cology 9（只读数据库直连）

支持 SQL Server、Oracle、MySQL，驱动均为纯 Python（`pymssql`、`oracledb` thin 模式、`pymysql`），不需要安装客户端。
后端服务器需要能访问 OA 数据库端口（默认 1433 / 1521 / 3306）。

### 4.1 创建只读账号

只需要对 `HrmSubCompany`、`HrmDepartment`、`HrmResource`、`HrmJobTitles` 四张表的 SELECT 权限。

SQL Server：

```sql
CREATE LOGIN ekb_reader WITH PASSWORD = '<强密码>', CHECK_POLICY = ON;
USE ecology;
CREATE USER ekb_reader FOR LOGIN ekb_reader;
GRANT SELECT ON dbo.HrmSubCompany TO ekb_reader;
GRANT SELECT ON dbo.HrmDepartment TO ekb_reader;
GRANT SELECT ON dbo.HrmResource TO ekb_reader;
GRANT SELECT ON dbo.HrmJobTitles TO ekb_reader;
```

Oracle（假设 OA 表在 `ECOLOGY` 用户下）：

```sql
CREATE USER ekb_reader IDENTIFIED BY "<强密码>";
GRANT CREATE SESSION TO ekb_reader;
GRANT SELECT ON ECOLOGY.HrmSubCompany TO ekb_reader;
GRANT SELECT ON ECOLOGY.HrmDepartment TO ekb_reader;
GRANT SELECT ON ECOLOGY.HrmResource TO ekb_reader;
GRANT SELECT ON ECOLOGY.HrmJobTitles TO ekb_reader;
-- 只读账号默认 schema 不是 ECOLOGY，可建同义词，或在「覆盖默认 SQL」中写 ECOLOGY.表名
CREATE SYNONYM ekb_reader.HrmSubCompany FOR ECOLOGY.HrmSubCompany;
CREATE SYNONYM ekb_reader.HrmDepartment FOR ECOLOGY.HrmDepartment;
CREATE SYNONYM ekb_reader.HrmResource FOR ECOLOGY.HrmResource;
CREATE SYNONYM ekb_reader.HrmJobTitles FOR ECOLOGY.HrmJobTitles;
```

Oracle 的「数据库名」填写**服务名**（如 `ORCL` / `ecology`）。

MySQL：

```sql
CREATE USER 'ekb_reader'@'<后端服务器IP>' IDENTIFIED BY '<强密码>';
GRANT SELECT ON ecology.HrmSubCompany TO 'ekb_reader'@'<后端服务器IP>';
GRANT SELECT ON ecology.HrmDepartment TO 'ekb_reader'@'<后端服务器IP>';
GRANT SELECT ON ecology.HrmResource TO 'ekb_reader'@'<后端服务器IP>';
GRANT SELECT ON ecology.HrmJobTitles TO 'ekb_reader'@'<后端服务器IP>';
```

### 4.2 映射规则

| 泛微 | 知识库 |
| --- | --- |
| 分部 `HrmSubCompany`（上级 `supsubcomid`） | 部门节点；可在配置中关闭「同步分部层级」 |
| 部门 `HrmDepartment`（上级 `supdepid`，无上级时挂在所属分部 `subcompanyid1` 下） | 部门 |
| `canceled=1`（已封存） | 已归档 |
| 人员 `HrmResource.status` 0~3（试用 / 正式 / 临时 / 试用延期） | 在职；4 及以上（解聘 / 离职 / 退休 / 无效）停用 |
| `loginid` / `workcode` | 账号 / 工号；`loginid` 为空时用工号作账号 |
| `jobtitle` → `HrmJobTitles.jobtitlename` | 职务（用户组「职务/<职务名>」） |
| 次账号 `accounttype=1`，`belongto` 指向主账号 | 主账号的兼职部门 |

### 4.3 覆盖默认 SQL

二开改过表结构时，在数据源配置「高级：覆盖默认 SQL」中改写分部 / 部门 / 人员三段查询，**列别名必须与默认 SQL 保持一致**。
只允许单条 SELECT（或 WITH）语句，包含写操作关键字会被拒绝。

## 5. Excel 导入

适合没有对接系统的组织或一次性初始化。在「组织同步」页下载模板，列如下：

| 列 | 说明 |
| --- | --- |
| 部门路径 | 必填，`/` 分隔，如 `集团/越南Flyknit/织造车间`，上级部门自动创建 |
| 账号 | 必填，登录账号 |
| 工号 / 邮箱 / 手机 | 选填，用于与已有账号匹配 |
| 姓名 | 必填 |
| 职务 | 选填，生成用户组「职务/<职务>」 |
| 是否主部门 | 一人多部门写多行，标记「是」的为主部门；不填则第一行为主部门 |
| 在职 | 是 / 否，默认是 |

上传后同样先预览再应用。表格里没有的人会被停用，预览时先确认停用名单。最多 50000 行。

## 6. 扫码登录

### 6.1 原理

Keycloak 没有内置企业微信 / 钉钉登录，后端内置了一个 OIDC 桥接（`/oidc/wecom`、`/oidc/dingtalk`），
Keycloak 把它当作「通用 OIDC 身份提供方」。扫码后桥接按 `user_identities` 找到已同步的本地用户，签发 RS256 id_token；
Keycloak 首次登录时自动创建账号并按用户名关联。后端仍只校验 Keycloak JWT。

**只有已同步、已启用且绑定了对应身份的用户能扫码登录。** 新员工需要先同步一次。

### 6.2 配置步骤

1. 设置环境变量（见第 8 节），尤其是 `PUBLIC_BASE_URL`（用户浏览器访问前端的地址）和 `KEYCLOAK_PUBLIC_URL`。
2. 新部署：`deploy/keycloak/realm-ekb.json` 已包含 `wecom`、`dingtalk` 两个身份提供方，首次启动自动导入。
3. 已有环境：在后端容器执行，写入身份提供方、首次登录流程和服务账号权限（可重复执行）：

   ```bash
   docker compose -f deploy/docker-compose.yml exec backend \
     python -m app.cli keycloak setup-idp --admin-user admin --admin-password '<Keycloak 管理员密码>'
   ```

   可用 `--providers wecom` 只配置企业微信；`--skip-service-account` 不给 `ekb-backend` 服务账号授予 `manage-users`
   （不授予则无法使用「密码登录」按钮）。
4. 在组织同步页配置企业微信 / 钉钉数据源并填写扫码登录相关字段。

### 6.3 登录入口

- Keycloak 登录页显示「企业微信」「钉钉」按钮。
- 直接跳转：`https://<前端>/?idp=wecom` 或 `?idp=dingtalk`，跳过 Keycloak 登录页。
- 在企业微信客户端（工作台）里打开时自动走企业微信，免扫码。
- `?idp=none`：强制显示 Keycloak 登录页（账号密码登录）。
- 同一种扫码登录（企业微信或钉钉）通常只有一个数据源启用（集团一般只有一个企业微信企业），无需额外配置。
  如果确实有多个启用的数据源，登录会返回 `OIDC_BRIDGE_AMBIGUOUS`：在 Keycloak 管理台
  「Identity providers → wecom / dingtalk → Authorization URL」末尾加上 `?source=<数据源ID>` 指定使用哪一个（重新执行 `setup-idp` 会覆盖该地址，需要再加一次）。

### 6.4 密码登录兜底

同步的用户默认没有 Keycloak 密码。管理员在「用户管理」点击「密码登录」，系统在 Keycloak 中创建或找到该账号，
生成 12 位临时密码（只显示一次，审计日志不记录密码），用户首次登录时必须修改。

## 7. 排障

| 错误码 / 现象 | 原因与处理 |
| --- | --- |
| 测试连接 60020 | 服务器出口 IP 不在企业微信「企业可信 IP」/ 钉钉白名单中 |
| 测试连接 48009 | 企业微信填的不是「通讯录同步」Secret |
| 测试连接 60011 | Secret / 应用没有通讯录范围或权限 |
| `无法连接泛微数据库` | 网络、端口、账号密码或 Oracle 服务名错误 |
| `查询失败（sql_users）` 等 | 表或列不存在（二开改过结构）或缺少 SELECT 权限，改写对应 SQL 或补授权 |
| 同步「已中止」 | 停用人数超过阈值，检查预览中的停用名单，确认无误后强制应用 |
| `SYNC_RUNNING` | 同一数据源已有同步在执行 |
| `DIRECTORY_MANAGED` | 字段由主数据源管理，请在源系统修改 |
| `OIDC_BRIDGE_UNMATCHED` | 扫码账号没有同步到知识库，先执行同步或检查可见范围 |
| `OIDC_BRIDGE_USER_DISABLED` | 账号在知识库中已停用（通常是离职） |
| `OIDC_BRIDGE_NOT_MEMBER` | 扫码的不是本企业成员 |
| `OIDC_BRIDGE_NOT_CONFIGURED` | 没有启用且配置了扫码登录的数据源 |
| `OIDC_BRIDGE_AMBIGUOUS` | 多个数据源启用了同一种扫码登录，在 IdP 授权地址加 `?source=<数据源ID>`（见 6.3） |
| `OIDC_BRIDGE_STATE` | 登录会话过期（10 分钟）或在另一个浏览器完成了扫码，返回重新登录 |
| `OIDC_BRIDGE_UPSTREAM` | 调用企业微信 / 钉钉接口失败，检查扫码登录应用的 Secret 与可信 IP |
| `OIDC_BRIDGE_REDIRECT_URI` | Keycloak 身份提供方的回调地址与 `KEYCLOAK_PUBLIC_URL` 不一致，重新执行 `setup-idp` |
| `KEYCLOAK_ORG_MISMATCH` | 「密码登录」时 Keycloak 中同名账号属于另一个组织 |
| 扫码后企业微信提示 redirect_uri 域名不一致 | 授权回调域 / 可信域名与 `PUBLIC_BASE_URL` 的域名不一致 |

## 8. 配置项

| 变量 | 说明 |
| --- | --- |
| `DIRECTORY_SECRET_KEY` | 加密数据源凭据的 Fernet 密钥，生产必填；更换后已保存的凭据需要重新填写。生成：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DIRECTORY_SYNC_MAX_DISABLE_RATIO` | 停用保护阈值，默认 `0.2` |
| `PUBLIC_BASE_URL` | 用户浏览器访问前端的地址，扫码回调与 OIDC issuer 由此生成 |
| `OIDC_BRIDGE_ENABLED` | 是否启用扫码登录桥接，默认 `true` |
| `OIDC_BRIDGE_SIGNING_KEY` | id_token 签名私钥（PEM，可用 `\n` 写成一行），生产必填。生成：`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048` |
| `OIDC_BRIDGE_CLIENT_SECRET` | Keycloak 调用桥接的客户端密钥，生产必填；后端与 Keycloak 容器必须一致 |
| `OIDC_BRIDGE_INTERNAL_URL` | Keycloak 容器访问后端的内部地址，默认 `http://backend:8000` |
| `KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET` | 「密码登录」使用的服务账号，默认 `ekb-backend` |
