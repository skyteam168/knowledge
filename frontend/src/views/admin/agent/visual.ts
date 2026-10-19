import { i18n, t } from '@/i18n'
import type { AclPermission, AgentRunDetail, PrincipalType } from '@/api/types'
import { permissionLabel, principalLabel } from '@/utils/document'
import { formatDateTime } from '@/utils/format'
import { applyEvent, newTurn, stepText, type AgentTurn } from './run'

// ---- tool results as tables ----------------------------------------------------------------

export interface ResultTable {
  title?: string
  headers: string[]
  rows: string[][]
}

const MAX_ROWS = 200
const PERMISSIONS = ['read', 'edit', 'manage']
const PRINCIPALS = ['user', 'group', 'role', 'dept']

function column(key: string): string {
  const path = `adminAgent.columns.${key}`
  return i18n.global.te(path) ? t(path) : key
}

function principalName(type: string): string {
  if (type === 'org') return t('adminAgent.result.everyone')
  return PRINCIPALS.includes(type) ? principalLabel(type as PrincipalType) : type
}

const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/

function scalar(key: string, value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'boolean') return t(value ? 'adminAgent.result.yes' : 'adminAgent.result.no')
  const text = String(value)
  if (ISO_TIME.test(text)) return formatDateTime(text)
  if ((key === 'permission' || key === 'default_permission') && PERMISSIONS.includes(text)) {
    return permissionLabel(text as AclPermission)
  }
  if (key === 'visibility' && ['restricted', 'org'].includes(text)) {
    return t(`knowledge.visibility.${text}`)
  }
  if (key === 'type') return principalName(text)
  return text
}

/** `[{type, name, permission}]` → "部门 IT → 编辑; …"; plain lists → "a、b". */
function cell(key: string, value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        item && typeof item === 'object'
          ? Object.entries(item as Record<string, unknown>)
              .map(([k, v]) => scalar(k, v))
              .filter(Boolean)
              .join(' · ')
          : scalar(key, item),
      )
      .join(t('layout.roleSeparator'))
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .map(
        ([k, v]) =>
          `${column(k)}: ${Array.isArray(v) ? v.map((x) => scalar(k, x)).join(' / ') : scalar(k, v)}`,
      )
      .join(' · ')
  }
  return scalar(key, value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function listTable(items: unknown[], title?: string): ResultTable {
  const rows = items.slice(0, MAX_ROWS)
  if (!rows.every(isRecord)) {
    return { title, headers: [column('value')], rows: rows.map((v) => [cell('value', v)]) }
  }
  const keys: string[] = []
  for (const row of rows) for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k)
  return {
    title,
    headers: keys.map(column),
    rows: rows.map((row) => keys.map((k) => cell(k, row[k]))),
  }
}

/** Tables for a query tool's raw result: lists become rows; objects become a field table + one table per list of records. */
export function resultTables(result: unknown): ResultTable[] {
  if (Array.isArray(result)) return result.length ? [listTable(result)] : []
  if (!isRecord(result)) return []
  const fields: string[][] = []
  const tables: ResultTable[] = []
  for (const [key, value] of Object.entries(result)) {
    if (Array.isArray(value) && value.length && value.every(isRecord)) {
      tables.push(listTable(value, column(key)))
    } else {
      fields.push([column(key), cell(key, value)])
    }
  }
  if (fields.length) {
    tables.unshift({ headers: [column('field'), column('value')], rows: fields })
  }
  return tables
}

// ---- mermaid -----------------------------------------------------------------------------------

/** Mermaid never auto-wraps CJK labels (no spaces) and clips them at `wrappingWidth`, so long
 * labels are broken into lines here, each well under that width. */
const INIT = '%%{init: {"flowchart": {"wrappingWidth": 480}}}%%'
const LINE_UNITS = 30

function wrap(text: string): string[] {
  const lines: string[] = []
  let line = ''
  let units = 0
  for (const ch of text) {
    const w = ch.charCodeAt(0) > 0x2e80 ? 2 : 1
    if (units + w > LINE_UNITS && line) {
      lines.push(line)
      line = ''
      units = 0
    }
    if (!line && ch === ' ') continue
    line += ch
    units += w
  }
  if (line) lines.push(line)
  return lines
}

/** Quoted mermaid label: no raw quotes, brackets or newlines from data; long text wrapped. */
export function label(text: string): string {
  const lines = wrap(text.replace(/[\r\n]+/g, ' ').slice(0, 120)).map((line) =>
    line.replace(/"/g, '#quot;').replace(/</g, '#lt;').replace(/>/g, '#gt;'),
  )
  return `"${lines.join('<br/>')}"`
}

interface Via {
  type: string
  name: string
  permission: string
}

function viaList(value: unknown): Via[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((v) => ({
    type: String(v.type ?? ''),
    name: String(v.name ?? ''),
    permission: String(v.permission ?? ''),
  }))
}

const perm = (p: string) => (PERMISSIONS.includes(p) ? permissionLabel(p as AclPermission) : p)

/** Permission chain diagram for `explain_user_access` / `get_kb_access`, or null. */
export function accessGraph(tool: string, result: unknown): string | null {
  if (!isRecord(result)) return null
  const lines: string[] = [INIT, 'graph LR']
  if (tool === 'explain_user_access' && Array.isArray(result.knowledge_bases)) {
    const kbs = result.knowledge_bases.filter(isRecord).slice(0, 30)
    if (!kbs.length) return null
    lines.push(`  U[${label(String(result.user ?? ''))}]`)
    const principals = new Map<string, string>()
    kbs.forEach((kb, i) => {
      lines.push(`  K${i}[(${label(String(kb.name ?? ''))})]`)
      for (const via of viaList(kb.via)) {
        const key = `${via.type}:${via.name}`
        let id = principals.get(key)
        if (!id) {
          id = `P${principals.size}`
          principals.set(key, id)
          const text =
            via.type === 'org' ? principalName('org') : `${principalName(via.type)} · ${via.name}`
          lines.push(`  ${id}(${label(text)})`)
          lines.push(`  U --> ${id}`)
        }
        lines.push(`  ${id} -- ${label(perm(via.permission))} --> K${i}`)
      }
    })
    return lines.join('\n')
  }
  if (tool === 'get_kb_access' && Array.isArray(result.entries)) {
    const entries = result.entries.filter(isRecord).slice(0, 40)
    lines.push(`  K[(${label(String(result.knowledge_base ?? ''))})]`)
    if (result.visibility === 'org') {
      lines.push(`  ORG(${label(principalName('org'))}) -- ${label(perm('read'))} --> K`)
    }
    if (!entries.length && result.visibility !== 'org') return null
    entries.forEach((e, i) => {
      const name = `${principalName(String(e.type ?? ''))} · ${String(e.name ?? '')}`
      lines.push(`  E${i}(${label(name)}) -- ${label(perm(String(e.permission ?? '')))} --> K`)
      if (e.active === false) lines.push(`  class E${i} inactive`)
    })
    lines.push('  classDef inactive stroke-dasharray: 4 3,opacity:0.6')
    return lines.join('\n')
  }
  return null
}

const STEP_CLASS: Record<string, string> = {
  done: 'done',
  running: 'running',
  failed: 'failed',
  rolled_back: 'failed',
  not_run: 'skipped',
}

/** Plan as a flowchart: confirm → steps (colored by status) → verified. */
export function planFlowchart(turn: AgentTurn): string {
  const plan = turn.plan
  if (!plan) return ''
  const lines = [INIT, 'flowchart TD', `  S([${label(t('adminAgent.plan.flowStart'))}])`]
  let prev = 'S'
  plan.steps.forEach((step, i) => {
    lines.push(`  N${i}[${label(`${i + 1}. ${stepText(step.tool, step.display)}`)}]`)
    lines.push(`  ${prev} --> N${i}`)
    const cls = STEP_CLASS[turn.steps[i]?.status ?? '']
    if (cls) lines.push(`  class N${i} ${cls}`)
    else if (step.risk === 'high') lines.push(`  class N${i} risky`)
    prev = `N${i}`
  })
  lines.push(`  E([${label(t('adminAgent.plan.flowEnd'))}])`, `  ${prev} --> E`)
  if (turn.outcome === 'done') lines.push('  class E done')
  if (turn.outcome === 'failed') lines.push('  class E failed')
  lines.push(
    '  classDef done fill:#e8ffea,stroke:#00b42a,color:#1f2329',
    '  classDef running fill:#eef3ff,stroke:#3370ff,color:#1f2329',
    '  classDef failed fill:#fff1f0,stroke:#f53f3f,color:#1f2329',
    '  classDef skipped fill:#f2f3f5,stroke:#c9cdd4,color:#86909c',
    '  classDef risky stroke:#f53f3f,stroke-width:2px',
  )
  return lines.join('\n')
}

// ---- history replay ------------------------------------------------------------------------

/** Rebuild a turn from a stored run so it renders exactly as it did live. */
export function replayTurn(run: AgentRunDetail, now = Date.now()): AgentTurn {
  const turn = newTurn()
  for (const e of run.events) applyEvent(turn, e.type, e.data)
  for (const e of run.exec_events) {
    if (e.type !== 'run' && e.type !== 'done') applyEvent(turn, e.type, e.data)
  }
  turn.runId = run.id
  if (run.status === 'cancelled') turn.outcome = 'cancelled'
  if (
    run.status === 'awaiting_approval' &&
    (!run.expires_at || new Date(run.expires_at).getTime() <= now)
  ) {
    turn.outcome = 'expired'
  }
  return turn
}
