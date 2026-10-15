# Keycloak 对接 AD / LDAP

平台不直接连接 AD。认证链路为：**AD → Keycloak 用户联邦（LDAP）→ OIDC 令牌 → 后端校验 JWT**。后端只读取令牌中的声明，首次登录或声明变化时自动同步本地用户、用户组和角色。

## 1. 后端依赖的令牌声明

| 声明 | 来源（Keycloak） | 后端用途 |
|---|---|---|
| `sub` | 用户 ID | 本地用户绑定（`users.keycloak_sub`） |
| `preferred_username` | 用户名 | 本地用户名（组织内唯一） |
| `email`、`name` | 用户属性 | 展示 |
| `org_id` | 用户属性 `org_id`（`ekb-frontend` 客户端的 *org_id* mapper） | 租户。缺省时用 `AUTH_DEFAULT_ORG_CODE`；组织不存在时按 `AUTH_AUTO_CREATE_ORG` 自动创建或拒绝登录 |
| `groups` | 组成员关系（*groups* mapper，`full.path=false`，只取组名） | 同步为本地用户组（来源 `keycloak`），用于 ACL 授权 |
| `realm_access.roles` | Realm 角色 | 与本地同名角色（如 `kb_admin`、`kb_editor`、`kb_viewer`）关联；`platform_admin` 直接从令牌判断 |
| `aud` 包含 `ekb-backend` | *audience-ekb-backend* mapper | 后端校验受众 |

所以 AD 对接的目标就是：让 AD 用户在 Keycloak 中带上 **org_id 属性、组成员关系和 realm 角色**。

## 2. 前置条件

- AD 域控地址与 LDAPS 证书（建议 636 端口 LDAPS；如 CA 为企业内部 CA，需导入 Keycloak 信任库，见第 6 节）。
- 只读服务账号，例如 `CN=svc-keycloak,OU=Service Accounts,DC=corp,DC=example,DC=com`，具备读取用户与组的权限。
- 规划好：用户所在 OU、用于授权的安全组所在 OU、AD 组与平台角色的对应关系。

## 3. 配置用户联邦

Keycloak 管理台 → 选择 realm `ekb` → **User federation** → **Add Ldap providers**：

| 配置项 | 建议值 |
|---|---|
| Vendor | Active Directory |
| Connection URL | `ldaps://dc01.corp.example.com:636`（多个域控用空格分隔） |
| Bind type / Bind DN / Credentials | simple / 服务账号 DN / 密码 |
| Edit mode | `READ_ONLY`（以 AD 为准，密码在 AD 修改） |
| Users DN | `OU=Staff,DC=corp,DC=example,DC=com` |
| Username LDAP attribute | `sAMAccountName`（或 `userPrincipalName`） |
| RDN LDAP attribute | `cn` |
| UUID LDAP attribute | `objectGUID` |
| User object classes | `person, organizationalPerson, user` |
| User LDAP filter | 只同步启用的、属于指定组的账号，例如 `(&(!(userAccountControl:1.2.840.113556.1.4.803:=2))(memberOf=CN=EKB-Users,OU=Groups,DC=corp,DC=example,DC=com))` |
| Search scope | Subtree |
| Import users | On |
| Sync registrations | Off |
| Periodic full sync / changed users sync | 例如每天全量、每 15 分钟增量 |
| Allow Kerberos authentication | 需要 Windows 集成登录（SPNEGO）时开启并配置 keytab |

保存后点击 **Test connection** 与 **Test authentication**，再执行 **Sync all users**。

## 4. 映射器（Mappers）

在该 LDAP provider 的 **Mappers** 页签添加：

### 4.1 基本属性

默认已有 `username`、`email`（`mail`）、`first name`（`givenName`）、`last name`（`sn`）映射器，确认属性名正确即可。

### 4.2 组织（org_id）

- **单租户**：添加 `hardcoded-attribute-mapper`，User Model Attribute = `org_id`，Attribute Value = 组织编码（与平台中组织的 `code` 一致，例如 `default`）。
- **多租户 / 多法人**：添加 `user-attribute-ldap-mapper`，把 AD 中区分组织的属性（如 `company`、`extensionAttribute1`）映射到 User Model Attribute `org_id`，`Read only = On`。AD 属性的取值必须等于平台组织编码。

令牌中的 `org_id` 由 `ekb-frontend` 客户端已有的 *org_id* mapper 输出，无需再改客户端。

### 4.3 用户组（用于 ACL）

添加 `group-ldap-mapper`：

| 配置项 | 建议值 |
|---|---|
| LDAP Groups DN | `OU=EKB,OU=Groups,DC=corp,DC=example,DC=com`（只同步平台相关的组） |
| Group Name LDAP Attribute | `cn` |
| Group Object Classes | `group` |
| Membership LDAP Attribute | `member` |
| Membership Attribute Type | `DN` |
| User Groups Retrieve Strategy | `LOAD_GROUPS_BY_MEMBER_ATTRIBUTE_RECURSIVELY`（支持嵌套组） |
| Mode | `READ_ONLY` |
| Preserve Group Inheritance | Off（后端只使用组名，扁平结构更清晰） |

保存后点击 **Sync LDAP groups to Keycloak**。用户登录后令牌的 `groups` 声明包含这些组名，后端自动创建同名本地用户组（来源 `keycloak`），之后即可在知识库 / 文档 ACL 中授权给这些组。

注意：后端按**组名**匹配，不同 OU 下的同名组会被视为同一个组，请保证纳入同步范围的组名唯一。

### 4.4 角色

推荐“AD 组 → Keycloak 组 → Realm 角色”：

1. 在 Keycloak **Groups** 中，对同步过来的组（如 `EKB-Admins`、`EKB-Editors`、`EKB-Users`）打开 **Role mapping**，分别分配 `kb_admin`、`kb_editor`、`kb_viewer`。
2. `platform_admin`（跨组织管理）只分配给极少数运维账号，建议使用 Keycloak 本地账号而非 AD 账号。

也可以用 `role-ldap-mapper` 把某个 OU 下的 AD 组直接映射为 realm 角色；此时 AD 组名必须与平台角色编码一致。

角色或组变化后，用户下一次刷新令牌时（`accessTokenLifespan` 默认 30 分钟）后端自动同步，并清理该用户的权限缓存。

## 5. 生产环境的 realm 设置

仓库中的 `deploy/keycloak/realm-ekb.json` 包含演示用户和本地开发地址，生产环境需要：

- **Realm settings → General**：`Require SSL` = `external requests`。
- **Users**：删除 `alice`、`bob`、`carol` 等演示账号。
- **Clients → ekb-frontend**：
  - Valid redirect URIs / Web origins / Post logout redirect URIs 改为 `https://kb.example.com/*` 与 `https://kb.example.com`；
  - `Direct access grants` 关闭（仅压测时临时开启）。
- **Clients → ekb-backend**：重新生成 client secret（当前后端只校验 JWT，不使用该 secret）。
- **Authentication → Policies**：按企业要求设置密码策略、暴力破解保护（Realm settings → Security defenses → Brute force detection）。
- **Sessions**：SSO Session Idle / Max 与企业安全策略一致。

配置完成后通过 **Realm settings → Action → Partial export**（包含组、角色、客户端）导出为生产 realm 文件，路径填入 `.env.prod` 的 `KEYCLOAK_REALM_FILE`，用于新环境初始化；运行中的环境以 `keycloak` 数据库为准（见[备份与恢复](backup-restore.md)）。

## 6. LDAPS 证书

企业内部 CA 签发的域控证书需要加入 Keycloak 信任库。把 CA 证书（PEM）挂载进容器并配置 truststore：

```yaml
# docker-compose.prod.yml → keycloak
    environment:
      KC_TRUSTSTORE_PATHS: /opt/keycloak/conf/truststores/corp-ca.pem
    volumes:
      - ./keycloak/corp-ca.pem:/opt/keycloak/conf/truststores/corp-ca.pem:ro
```

LDAP provider 中 `Use Truststore SPI` 保持 `Always`。

## 7. 验证

1. User federation 页 **Test authentication** 成功，**Sync all users** 有导入数量。
2. 用一个 AD 账号登录平台：右上角显示正确姓名。
3. Keycloak → Clients → ekb-frontend → **Client scopes → Evaluate**，选择该用户，查看生成的 access token：包含 `org_id`、`groups`、`realm_access.roles`，`aud` 含 `ekb-backend`。
4. 平台 管理 → 用户管理：该用户在正确的组织下，用户组 / 角色来源为 `keycloak`。
5. 审计日志中出现 `user.provision` 记录。
6. 对该用户所在组授权一个受限知识库，确认能搜索 / 问答到其中内容，组外用户不能（可直接运行 ACL 回归用例思路做人工抽检）。

## 8. 故障排查

| 现象 | 排查 |
|---|---|
| 登录提示用户名或密码错误 | User federation 的 Users DN / User LDAP filter 是否包含该用户；`Test authentication`；AD 账号是否锁定 |
| 登录后 401 `INVALID_TOKEN` | 后端 `KEYCLOAK_PUBLIC_URL` 必须与令牌 `iss` 完全一致（协议、主机、端口）；时钟偏差（`JWT_LEEWAY_SECONDS`） |
| 401 `ORG_NOT_FOUND` | 令牌缺少 `org_id` 且默认组织不存在，或 `AUTH_AUTO_CREATE_ORG=false` 时组织未预先创建 |
| 403 `ORG_MISMATCH` | 同一用户的 `org_id` 变了：账号已绑定原组织，需要管理员在平台中处理 |
| 用户组没有同步 | 令牌中是否有 `groups`；group-ldap-mapper 的 Groups DN；执行 “Sync LDAP groups to Keycloak” |
| 角色权限不生效 | Keycloak 组的 Role mapping；平台中是否存在同名角色；等待令牌刷新或重新登录 |
