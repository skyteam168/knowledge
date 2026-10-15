import type { DirectorySourceType, RecordSource, SyncStatus } from '@/api/types'

export const SOURCE_LABEL: Record<RecordSource, string> = {
  local: '本地',
  keycloak: 'Keycloak',
  wecom: '企业微信',
  dingtalk: '钉钉',
  weaver: '泛微OA',
  excel: 'Excel',
}

export const SOURCE_TYPES: { value: DirectorySourceType; label: string; desc: string }[] = [
  { value: 'wecom', label: '企业微信', desc: '通讯录 API 同步，支持扫码登录' },
  { value: 'dingtalk', label: '钉钉', desc: '通讯录 API 同步，支持扫码登录' },
  {
    value: 'weaver',
    label: '泛微 e-cology 9',
    desc: '只读数据库直连（SQL Server / Oracle / MySQL）',
  },
  { value: 'excel', label: 'Excel 导入', desc: '按模板上传，适合没有对接系统的组织' },
]

export const STATUS_INFO: Record<
  SyncStatus,
  { label: string; type: 'success' | 'danger' | 'warning' | 'info' }
> = {
  running: { label: '进行中', type: 'info' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  aborted: { label: '已中止', type: 'warning' },
}

export const ACTION_LABEL: Record<string, string> = {
  create: '新增',
  adopt: '接管本地',
  rename: '改名',
  move: '移动',
  order: '排序',
  restore: '恢复',
  archive: '归档',
  update: '更新',
  disable: '停用',
  bind: '绑定身份',
  remove: '解绑',
  departments: '部门',
  title: '职务',
  display_name: '姓名',
  email: '邮箱',
  mobile: '手机',
  employee_no: '工号',
  job_title: '职务',
  source: '来源',
  username: '账号',
}

export const MATCH_LABEL: Record<string, string> = {
  employee_no: '工号',
  mobile: '手机',
  email: '邮箱',
  username: '账号',
}

export interface ConfigField {
  key: string
  label: string
  type?: 'text' | 'password' | 'number' | 'select' | 'switch' | 'textarea'
  required?: boolean
  placeholder?: string
  help?: string
  options?: { label: string; value: string }[]
  group?: string
}

export const CONFIG_FIELDS: Record<DirectorySourceType, ConfigField[]> = {
  wecom: [
    {
      key: 'corp_id',
      label: '企业 ID (CorpID)',
      required: true,
      help: '管理后台 → 我的企业 → 企业信息',
    },
    {
      key: 'contacts_secret',
      label: '通讯录同步 Secret',
      type: 'password',
      required: true,
      help: '管理工具 → 通讯录同步 → 查看 Secret；服务器出口 IP 需加入企业可信 IP',
    },
    { key: 'root_department_id', label: '根部门 ID', type: 'number', placeholder: '1' },
    {
      key: 'employee_no_attr',
      label: '工号字段名',
      placeholder: '工号',
      help: '成员自定义字段中保存工号的字段名称',
    },
    { key: 'agent_id', label: '扫码登录应用 AgentId', group: '扫码登录（可选）' },
    {
      key: 'agent_secret',
      label: '扫码登录应用 Secret',
      type: 'password',
      group: '扫码登录（可选）',
    },
  ],
  dingtalk: [
    { key: 'app_key', label: 'AppKey (Client ID)', required: true },
    { key: 'app_secret', label: 'AppSecret (Client Secret)', type: 'password', required: true },
    { key: 'root_dept_id', label: '根部门 ID', type: 'number', placeholder: '1' },
  ],
  weaver: [
    {
      key: 'db_type',
      label: '数据库类型',
      type: 'select',
      required: true,
      options: [
        { label: 'SQL Server', value: 'sqlserver' },
        { label: 'Oracle', value: 'oracle' },
        { label: 'MySQL', value: 'mysql' },
      ],
    },
    { key: 'host', label: '主机', required: true },
    { key: 'port', label: '端口', type: 'number', placeholder: '默认 1433 / 1521 / 3306' },
    { key: 'database', label: '数据库名 / Oracle 服务名', required: true, placeholder: 'ecology' },
    { key: 'username', label: '只读账号', required: true },
    { key: 'password', label: '密码', type: 'password', required: true },
    { key: 'include_subcompanies', label: '同步分部层级', type: 'switch' },
    {
      key: 'sql_subcompanies',
      label: '分部 SQL',
      type: 'textarea',
      group: '高级：覆盖默认 SQL（二开改过表结构时使用，列名需保持一致）',
      placeholder:
        'SELECT id, subcompanyname AS name, supsubcomid AS parent_id, showorder AS sort_order, canceled FROM HrmSubCompany',
    },
    {
      key: 'sql_departments',
      label: '部门 SQL',
      type: 'textarea',
      group: '高级：覆盖默认 SQL（二开改过表结构时使用，列名需保持一致）',
      placeholder:
        'SELECT id, departmentname AS name, supdepid AS parent_id, subcompanyid1 AS subcompany_id, showorder AS sort_order, canceled FROM HrmDepartment',
    },
    {
      key: 'sql_users',
      label: '人员 SQL',
      type: 'textarea',
      group: '高级：覆盖默认 SQL（二开改过表结构时使用，列名需保持一致）',
      placeholder:
        'SELECT r.id, r.loginid, r.workcode, r.lastname AS name, r.email, r.mobile, r.departmentid, r.status, r.accounttype, r.belongto, j.jobtitlename AS title FROM HrmResource r LEFT JOIN HrmJobTitles j ON j.id = r.jobtitle',
    },
  ],
  excel: [],
}

export function statLine(
  stats: Record<string, number> | undefined,
  keys: [string, string][],
): string {
  if (!stats) return '—'
  const parts = keys
    .filter(([k]) => (stats[k] ?? 0) > 0)
    .map(([k, label]) => `${label} ${stats[k]}`)
  return parts.length ? parts.join('，') : '无变化'
}

export const DEPT_STAT_KEYS: [string, string][] = [
  ['created', '新增'],
  ['updated', '更新'],
  ['adopted', '接管'],
  ['restored', '恢复'],
  ['archived', '归档'],
]
export const USER_STAT_KEYS: [string, string][] = [
  ['created', '新增'],
  ['updated', '更新'],
  ['adopted', '接管'],
  ['restored', '恢复'],
  ['disabled', '停用'],
]
export const IDENTITY_STAT_KEYS: [string, string][] = [
  ['bound', '新绑定'],
  ['kept', '已绑定'],
  ['removed', '解绑'],
  ['unmatched', '未匹配'],
]
