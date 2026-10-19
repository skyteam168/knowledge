import { getValidToken, login } from '@/auth/client'
import { currentLocale, t } from '@/i18n'
import { SseParser } from '@/utils/sse'
import { HttpError, del, get, isApiErrorBody } from './http'
import type { AgentMessage, AgentRun, AgentRunDetail, Page } from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export type AgentEventHandler = (type: string, data: Record<string, unknown>) => void

async function stream(
  path: string,
  body: unknown,
  onEvent: AgentEventHandler,
  signal?: AbortSignal,
): Promise<void> {
  const token = await getValidToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    'Accept-Language': currentLocale(),
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    if (resp.status === 401) void login()
    const data: unknown = await resp.json().catch(() => null)
    throw isApiErrorBody(data)
      ? new HttpError(resp.status, data)
      : new HttpError(resp.status, {
          code: `HTTP_${resp.status}`,
          message: t('layout.http.failed', { status: resp.status }),
          detail: data,
          trace_id: resp.headers.get('x-trace-id'),
        })
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  const dispatch = (event: { event: string; data: string }) => {
    try {
      onEvent(event.event, JSON.parse(event.data) as Record<string, unknown>)
    } catch {
      /* ignore malformed events */
    }
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    parser.push(decoder.decode(value, { stream: true })).forEach(dispatch)
  }
  parser.push(decoder.decode()).forEach(dispatch)
  parser.flush().forEach(dispatch)
}

/** understand → clarify → query/answer → resolve → plan → risk → approval (SSE). */
export const startAgentRun = (
  message: string,
  history: AgentMessage[],
  onEvent: AgentEventHandler,
  signal?: AbortSignal,
) => stream('/admin/agent/runs', { message, history }, onEvent, signal)

/** approval → execute → verify → report (SSE). */
export const executeAgentRun = (
  runId: string,
  acknowledgeRisk: boolean,
  onEvent: AgentEventHandler,
) => stream(`/admin/agent/runs/${runId}/execute`, { acknowledge_risk: acknowledgeRisk }, onEvent)

export const cancelAgentRun = (runId: string) =>
  del<void>(`/admin/agent/runs/${runId}`, { silent: true })

/** The current admin's own runs, newest first. */
export const listAgentRuns = (page = 1, size = 20) =>
  get<Page<AgentRun>>('/admin/agent/runs', { params: { page, size } })

export const getAgentRun = (runId: string) => get<AgentRunDetail>(`/admin/agent/runs/${runId}`)
