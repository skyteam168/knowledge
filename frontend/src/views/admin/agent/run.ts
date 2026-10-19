import { t } from '@/i18n'
import type {
  AclPermission,
  AgentIssue,
  AgentOutcome,
  AgentPlan,
  AgentStage,
  AgentStageStatus,
  AgentStepStatus,
  PrincipalType,
} from '@/api/types'
import { permissionLabel, principalLabel } from '@/utils/document'

export interface StageState {
  stage: AgentStage
  status: AgentStageStatus
  durationMs?: number
  detail: Record<string, unknown>
}

export interface ToolCall {
  id: string
  tool: string
  args: Record<string, unknown>
  status: 'running' | 'done' | 'failed'
  durationMs?: number
  count?: number | null
  result?: unknown
  error?: AgentIssue
}

export interface StepState {
  status: AgentStepStatus
  durationMs?: number
  output?: Record<string, string>
  error?: AgentIssue
  check?: { ok: boolean; code: string; params: Record<string, string> }
}

/** One assistant turn, built incrementally from workflow events. */
export interface AgentTurn {
  runId?: string
  stages: StageState[]
  thoughts: string[]
  tools: ToolCall[]
  clarify: AgentIssue[]
  answer?: string
  plan?: AgentPlan
  steps: StepState[]
  outcome?: AgentOutcome
  error?: AgentIssue
  executing: boolean
}

export function newTurn(): AgentTurn {
  return { stages: [], thoughts: [], tools: [], clarify: [], steps: [], executing: false }
}

export function applyEvent(turn: AgentTurn, type: string, data: Record<string, unknown>): void {
  switch (type) {
    case 'run':
      turn.runId = String(data.run_id)
      break
    case 'stage': {
      const stage = data.stage as AgentStage
      const entry: StageState = {
        stage,
        status: data.status as AgentStageStatus,
        durationMs: data.duration_ms as number | undefined,
        detail: (data.detail as Record<string, unknown>) ?? {},
      }
      const existing = turn.stages.findIndex((s) => s.stage === stage)
      if (existing >= 0) turn.stages.splice(existing, 1, entry)
      else turn.stages.push(entry)
      break
    }
    case 'thought':
      turn.thoughts.push(String(data.text ?? ''))
      break
    case 'tool': {
      const id = String(data.id)
      const current = turn.tools.find((c) => c.id === id)
      const next: ToolCall = {
        ...(current ?? { id, tool: String(data.tool), args: {} }),
        ...(data.args ? { args: data.args as Record<string, unknown> } : {}),
        status: data.status as ToolCall['status'],
        durationMs: data.duration_ms as number | undefined,
        count: data.count as number | null | undefined,
        result: data.result,
        error: data.error as AgentIssue | undefined,
      }
      if (current) Object.assign(current, next)
      else turn.tools.push(next)
      break
    }
    case 'clarify':
      turn.clarify = (data.items as AgentIssue[]) ?? []
      break
    case 'answer':
      turn.answer = String(data.text ?? '')
      break
    case 'plan':
      turn.plan = data as unknown as AgentPlan
      turn.steps = turn.plan.steps.map(() => ({ status: 'pending' }))
      break
    case 'step': {
      const step = turn.steps[data.index as number]
      if (!step) break
      step.status = data.status as AgentStepStatus
      if (data.duration_ms != null) step.durationMs = data.duration_ms as number
      if (data.output) step.output = data.output as Record<string, string>
      if (data.error) step.error = data.error as AgentIssue
      break
    }
    case 'verify': {
      const step = turn.steps[data.index as number]
      if (step) step.check = data as unknown as StepState['check']
      break
    }
    case 'report':
      turn.outcome = data.outcome as AgentOutcome
      break
    case 'error':
      turn.error = data as unknown as AgentIssue
      break
  }
}

// ---- localization helpers ----------------------------------------------------------------

const PERMISSIONS = ['read', 'edit', 'manage']
const VISIBILITIES = ['restricted', 'org']

function localizeValue(key: string, value: string): string {
  if ((key === 'permission' || key === 'from' || key === 'to') && PERMISSIONS.includes(value)) {
    return permissionLabel(value as AclPermission)
  }
  if (key === 'visibility' && VISIBILITIES.includes(value))
    return t(`knowledge.visibility.${value}`)
  if (key === 'principal_type') return principalLabel(value as PrincipalType)
  if (key === 'level') return t(`adminAgent.risk.${value}`)
  if (key === 'task') return t(`adminAgent.tasks.${value}`)
  if (key === 'fields') {
    return value
      .split(',')
      .map((f) => t(`adminAgent.fields.${f}`))
      .join(t('layout.roleSeparator'))
  }
  if (key === 'intent') return t(`adminAgent.intent.${value}`)
  if (key === 'mode' && ['tools', 'json'].includes(value)) return t(`adminAgent.mode.${value}`)
  if (key === 'parent' && value === '-') return t('adminAgent.result.topLevel')
  return value
}

export function localized(params: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).map(([k, v]) => [
      k,
      Array.isArray(v)
        ? v
            .map((x) => localizeValue(k === 'tasks' ? 'task' : k, String(x)))
            .join(t('layout.roleSeparator'))
        : localizeValue(k, String(v ?? '')),
    ]),
  )
}

export function stepText(tool: string, display: Record<string, string>): string {
  return t(`adminAgent.tools.${tool}`, localized(display))
}

export function issueText(issue: AgentIssue): string {
  if (issue.reason === 'verify_failed') return t('adminAgent.error.verify_failed')
  if (['plan_expired', 'risk_ack_required'].includes(issue.reason)) {
    return t(`adminAgent.error.${issue.reason}`)
  }
  return t(`adminAgent.clarify.reason.${issue.reason}`, localized(issue.params ?? {}))
}
