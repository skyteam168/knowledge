import type { LocaleModule } from '../index'

export default {
  'zh-CN': {
    filters: {
      keyword: '组名',
      query: '查询',
    },
    create: '新建用户组',
    empty: '暂无用户组',
    columns: {
      name: '组名',
      source: '来源',
      memberCount: '成员数',
    },
    source: {
      keycloak: 'Keycloak',
      local: '本地',
    },
    members: '成员',
    editor: {
      createTitle: '新建用户组',
      editTitle: '编辑用户组',
      name: '组名',
    },
    rules: {
      nameRequired: '请输入组名',
    },
    saveSuccess: '保存成功',
    deleteConfirm: '确定删除用户组「{name}」吗？',
    membersDialog: {
      title: '成员管理：{name}',
      keycloakHint: 'Keycloak 同步的成员会在用户下次登录时按令牌重新同步，此处仅维护本地成员',
      placeholder: '搜索用户名 / 姓名添加成员',
      option: '{name}（{username}）',
      updated: '成员已更新',
    },
  },
  en: {
    filters: {
      keyword: 'Group name',
      query: 'Search',
    },
    create: 'New user group',
    empty: 'No user groups',
    columns: {
      name: 'Group name',
      source: 'Source',
      memberCount: 'Members',
    },
    source: {
      keycloak: 'Keycloak',
      local: 'Local',
    },
    members: 'Members',
    editor: {
      createTitle: 'New user group',
      editTitle: 'Edit user group',
      name: 'Group name',
    },
    rules: {
      nameRequired: 'Enter a group name',
    },
    saveSuccess: 'Saved',
    deleteConfirm: 'Delete user group "{name}"?',
    membersDialog: {
      title: 'Manage members: {name}',
      keycloakHint:
        "Members synced from Keycloak are re-synced from the token at the user's next sign-in; only local members are maintained here",
      placeholder: 'Search by username / name to add members',
      option: '{name} ({username})',
      updated: 'Members updated',
    },
  },
} satisfies LocaleModule
