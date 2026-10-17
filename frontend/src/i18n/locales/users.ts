import type { LocaleModule } from '../index'

/** Users page; `source` labels are shared with other directory-backed admin pages. */
export default {
  'zh-CN': {
    source: {
      local: '本地',
      keycloak: 'Keycloak',
      wecom: '企业微信',
      dingtalk: '钉钉',
      weaver: '泛微OA',
      excel: 'Excel',
    },
    filters: {
      keyword: '用户名 / 姓名 / 邮箱',
      department: '部门（含下级）',
      query: '查询',
    },
    status: {
      disabled: '禁用',
    },
    columns: {
      user: '用户',
      department: '部门',
      primary: '主',
      jobTitle: '职务',
      source: '来源',
      lastLogin: '最近登录',
    },
    keycloak: {
      bound: '已绑定',
      pending: '待登录',
    },
    actions: {
      precreate: '预置用户',
      passwordLogin: '密码登录',
      roles: '角色',
      groups: '用户组',
      disable: '禁用',
    },
    empty: '暂无用户',
    editor: {
      createTitle: '预置用户',
      editTitle: '编辑用户',
      precreateHint: '用户首次通过 Keycloak 登录时，将按用户名自动绑定该预置账号',
      managedHint:
        '该用户由「{source}」同步，资料与部门只读，请在源系统中修改；角色和本地用户组仍可在此分配。',
      username: '用户名',
      displayName: '姓名',
      employeeNo: '工号',
      email: '邮箱',
      mobile: '手机',
      jobTitle: '职务',
      primaryDepartment: '主部门',
      extraDepartments: '兼职部门',
      extraDepartmentsPlaceholder: '一人多部门时选择（权限按所有部门计算）',
      identities: '已绑定',
      identity: '{provider}：{id}',
    },
    rules: {
      usernameRequired: '请输入用户名',
      emailInvalid: '邮箱格式不正确',
    },
    saveSuccess: '保存成功',
    updated: '已更新',
    disableConfirm: '确定禁用用户「{name}」吗？',
    disableSuccess: '已禁用',
    passwordConfirm: {
      title: '开通密码登录',
      message:
        '将为「{name}」开通账号密码登录并生成临时密码（首次登录须修改）。已有 Keycloak 账号时会重置为新的临时密码。',
    },
    password: {
      title: '密码登录已开通',
      created: '账号 {username} 已在 Keycloak 中创建，临时密码（只显示这一次）：',
      reset: '账号 {username} 已重置密码，临时密码（只显示这一次）：',
      hint: '用户首次登录时必须修改密码。请通过安全渠道转交。',
      acknowledge: '我已记下',
    },
    assign: {
      rolesTitle: '分配角色：{username}',
      groupsTitle: '分配用户组：{username}',
      hint: '此处仅管理本地分配；来自 Keycloak 的角色/组在每次登录时同步',
      roleOption: '{name}（{code}）',
    },
  },
  en: {
    source: {
      local: 'Local',
      keycloak: 'Keycloak',
      wecom: 'WeCom',
      dingtalk: 'DingTalk',
      weaver: 'Weaver OA',
      excel: 'Excel',
    },
    filters: {
      keyword: 'Username / name / email',
      department: 'Department (incl. sub-departments)',
      query: 'Search',
    },
    status: {
      disabled: 'Disabled',
    },
    columns: {
      user: 'User',
      department: 'Department',
      primary: 'Primary',
      jobTitle: 'Job title',
      source: 'Source',
      lastLogin: 'Last sign-in',
    },
    keycloak: {
      bound: 'Linked',
      pending: 'Awaiting sign-in',
    },
    actions: {
      precreate: 'Pre-create user',
      passwordLogin: 'Password sign-in',
      roles: 'Roles',
      groups: 'User groups',
      disable: 'Disable',
    },
    empty: 'No users',
    editor: {
      createTitle: 'Pre-create user',
      editTitle: 'Edit user',
      precreateHint:
        'When the user first signs in via Keycloak, they are linked to this pre-created account by username',
      managedHint:
        'This user is synced from {source}. Profile and departments are read-only; edit them in the source system. Roles and local user groups can still be assigned here.',
      username: 'Username',
      displayName: 'Name',
      employeeNo: 'Employee ID',
      email: 'Email',
      mobile: 'Mobile',
      jobTitle: 'Job title',
      primaryDepartment: 'Primary department',
      extraDepartments: 'Other departments',
      extraDepartmentsPlaceholder:
        'For users in several departments (permissions cover all of them)',
      identities: 'Linked',
      identity: '{provider}: {id}',
    },
    rules: {
      usernameRequired: 'Enter a username',
      emailInvalid: 'Invalid email address',
    },
    saveSuccess: 'Saved',
    updated: 'Updated',
    disableConfirm: 'Disable user "{name}"?',
    disableSuccess: 'Disabled',
    passwordConfirm: {
      title: 'Enable password sign-in',
      message:
        'Password sign-in will be enabled for "{name}" with a temporary password (must be changed at first sign-in). If a Keycloak account already exists, its password is reset to a new temporary one.',
    },
    password: {
      title: 'Password sign-in enabled',
      created:
        'Account {username} has been created in Keycloak. Temporary password (shown only once):',
      reset: 'Password of account {username} has been reset. Temporary password (shown only once):',
      hint: 'The user must change the password at first sign-in. Share it through a secure channel.',
      acknowledge: 'I have saved it',
    },
    assign: {
      rolesTitle: 'Assign roles: {username}',
      groupsTitle: 'Assign user groups: {username}',
      hint: 'Only local assignments are managed here; roles and groups from Keycloak sync at every sign-in',
      roleOption: '{name} ({code})',
    },
  },
} satisfies LocaleModule
