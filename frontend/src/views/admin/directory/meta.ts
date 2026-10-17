import type { DirectorySourceType, RecordSource, SyncStatus } from '@/api/types'
import { t } from '@/i18n'

const RECORD_SOURCES: RecordSource[] = ['local', 'keycloak', 'wecom', 'dingtalk', 'weaver', 'excel']

export function sourceLabel(source: RecordSource): string {
  return t(`directory.source.${source}`)
}

/** Each read translates with the current locale; unknown keys stay `undefined`. */
export const SOURCE_LABEL = Object.defineProperties(
  {} as Record<RecordSource, string>,
  Object.fromEntries(
    RECORD_SOURCES.map((s) => [s, { enumerable: true, get: () => sourceLabel(s) }]),
  ),
)

const SOURCE_TYPE_VALUES: DirectorySourceType[] = ['wecom', 'dingtalk', 'weaver', 'excel']

export interface SourceTypeOption {
  value: DirectorySourceType
  label: string
  desc: string
}

export function sourceTypes(): SourceTypeOption[] {
  return SOURCE_TYPE_VALUES.map((value) => ({
    value,
    label: t(`directory.type.${value}.label`),
    desc: t(`directory.type.${value}.desc`),
  }))
}

type StatusTagType = 'success' | 'danger' | 'warning' | 'info'

const STATUS_TYPE: Record<SyncStatus, StatusTagType> = {
  running: 'info',
  succeeded: 'success',
  failed: 'danger',
  aborted: 'warning',
}

export function statusInfo(status: SyncStatus): { label: string; type: StatusTagType } {
  return { label: t(`directory.status.${status}`), type: STATUS_TYPE[status] }
}

const ACTIONS = new Set([
  'create',
  'adopt',
  'rename',
  'move',
  'order',
  'restore',
  'archive',
  'update',
  'disable',
  'bind',
  'remove',
  'departments',
  'title',
  'display_name',
  'email',
  'mobile',
  'employee_no',
  'job_title',
  'source',
  'username',
])

export function actionLabel(action: string): string {
  return ACTIONS.has(action) ? t(`directory.action.${action}`) : action
}

const MATCHES = new Set(['employee_no', 'mobile', 'email', 'username'])

export function matchLabel(match: string): string {
  return MATCHES.has(match) ? t(`directory.match.${match}`) : match
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

/** WeCom custom attribute name holding the employee number; a config value, not UI text. */
export const WECOM_EMPLOYEE_NO_ATTR = '工号'

type FieldDef = Omit<ConfigField, 'label' | 'help' | 'placeholder' | 'group'> & {
  help?: true
  /** `true` = translated `directory.field.<key>.placeholder`; a string is shown verbatim. */
  placeholder?: string | true
  group?: 'login' | 'advancedSql'
}

const FIELD_DEFS: Record<DirectorySourceType, FieldDef[]> = {
  wecom: [
    { key: 'corp_id', required: true, help: true },
    { key: 'contacts_secret', type: 'password', required: true, help: true },
    { key: 'root_department_id', type: 'number', placeholder: '1' },
    { key: 'employee_no_attr', placeholder: WECOM_EMPLOYEE_NO_ATTR, help: true },
    { key: 'agent_id', group: 'login' },
    { key: 'agent_secret', type: 'password', group: 'login' },
  ],
  dingtalk: [
    { key: 'app_key', required: true },
    { key: 'app_secret', type: 'password', required: true },
    { key: 'root_dept_id', type: 'number', placeholder: '1' },
  ],
  weaver: [
    {
      key: 'db_type',
      type: 'select',
      required: true,
      options: [
        { label: 'SQL Server', value: 'sqlserver' },
        { label: 'Oracle', value: 'oracle' },
        { label: 'MySQL', value: 'mysql' },
      ],
    },
    { key: 'host', required: true },
    { key: 'port', type: 'number', placeholder: true },
    { key: 'database', required: true, placeholder: 'ecology' },
    { key: 'username', required: true },
    { key: 'password', type: 'password', required: true },
    { key: 'include_subcompanies', type: 'switch' },
    {
      key: 'sql_subcompanies',
      type: 'textarea',
      group: 'advancedSql',
      placeholder:
        'SELECT id, subcompanyname AS name, supsubcomid AS parent_id, showorder AS sort_order, canceled FROM HrmSubCompany',
    },
    {
      key: 'sql_departments',
      type: 'textarea',
      group: 'advancedSql',
      placeholder:
        'SELECT id, departmentname AS name, supdepid AS parent_id, subcompanyid1 AS subcompany_id, showorder AS sort_order, canceled FROM HrmDepartment',
    },
    {
      key: 'sql_users',
      type: 'textarea',
      group: 'advancedSql',
      placeholder:
        'SELECT r.id, r.loginid, r.workcode, r.lastname AS name, r.email, r.mobile, r.departmentid, r.status, r.accounttype, r.belongto, j.jobtitlename AS title FROM HrmResource r LEFT JOIN HrmJobTitles j ON j.id = r.jobtitle',
    },
  ],
  excel: [],
}

export function configFields(type: DirectorySourceType): ConfigField[] {
  return FIELD_DEFS[type].map(({ help, placeholder, group, ...def }) => ({
    ...def,
    label: t(`directory.field.${def.key}.label`),
    help: help ? t(`directory.field.${def.key}.help`) : undefined,
    placeholder: placeholder === true ? t(`directory.field.${def.key}.placeholder`) : placeholder,
    group: group ? t(`directory.fieldGroup.${group}`) : undefined,
  }))
}

export function statLine(
  stats: Record<string, number> | undefined,
  keys: readonly string[],
): string {
  if (!stats) return '—'
  const parts = keys
    .filter((k) => (stats[k] ?? 0) > 0)
    .map((k) => t('directory.stat.item', { label: t(`directory.stat.${k}`), count: stats[k] }))
  return parts.length ? parts.join(t('directory.stat.separator')) : t('directory.stat.noChange')
}

export const DEPT_STAT_KEYS: readonly string[] = [
  'created',
  'updated',
  'adopted',
  'restored',
  'archived',
]
export const USER_STAT_KEYS: readonly string[] = [
  'created',
  'updated',
  'adopted',
  'restored',
  'disabled',
]
export const IDENTITY_STAT_KEYS: readonly string[] = ['bound', 'kept', 'removed', 'unmatched']
