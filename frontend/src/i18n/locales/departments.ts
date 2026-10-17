import type { LocaleModule } from '../index'

export default {
  'zh-CN': {
    tree: {
      title: '部门树',
      addRoot: '新增根部门',
      searchPlaceholder: '搜索部门（支持完整路径）',
      showArchived: '显示已归档（{count}）',
      empty: '暂无部门',
      archived: '已归档',
      addChild: '添加子部门',
    },
    members: {
      title: '「{name}」成员（含下级，共 {total} 人）',
      selectDepartment: '请选择部门',
      empty: '暂无成员',
      username: '用户名',
      displayName: '姓名',
      jobTitle: '职务',
    },
    editor: {
      createTitle: '新增部门',
      editTitle: '编辑部门',
      managedHint: '该部门由组织同步维护，名称和上级只读，请在源系统中修改。',
      name: '部门名称',
      parent: '上级部门',
      parentPlaceholder: '无（根部门）',
      sortOrder: '排序',
    },
    rules: {
      nameRequired: '请输入部门名称',
    },
    saveSuccess: '保存成功',
    deleteConfirm: '确定删除部门「{name}」吗？',
  },
  en: {
    tree: {
      title: 'Department tree',
      addRoot: 'Add root department',
      searchPlaceholder: 'Search departments (full path supported)',
      showArchived: 'Show archived ({count})',
      empty: 'No departments',
      archived: 'Archived',
      addChild: 'Add sub-department',
    },
    members: {
      title: 'Members of "{name}" (incl. sub-departments, {total} total)',
      selectDepartment: 'Select a department',
      empty: 'No members',
      username: 'Username',
      displayName: 'Name',
      jobTitle: 'Job title',
    },
    editor: {
      createTitle: 'Add department',
      editTitle: 'Edit department',
      managedHint:
        'This department is maintained by organization sync. Name and parent department are read-only; edit them in the source system.',
      name: 'Department name',
      parent: 'Parent department',
      parentPlaceholder: 'None (root department)',
      sortOrder: 'Sort order',
    },
    rules: {
      nameRequired: 'Enter a department name',
    },
    saveSuccess: 'Saved',
    deleteConfirm: 'Delete department "{name}"?',
  },
} satisfies LocaleModule
