import { getValidToken, login } from '@/auth/client'
import { SseParser, type SseEvent } from '@/utils/sse'
import { HttpError, del, get, isApiErrorBody, post, put } from './http'
import type {
  AskBody,
  ChatDoneEvent,
  ChatErrorEvent,
  ChatMetaEvent,
  ChatStep,
  Citation,
  CitationSource,
  Conversation,
  ConversationCreate,
  ConversationDetail,
  ConversationUpdate,
  FeedbackBody,
  KnowledgeGap,
  MessageFeedback,
  Page,
  PageParams,
} from './types'

const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export const listConversations = (params: PageParams & { keyword?: string } = {}) =>
  get<Page<Conversation>>('/chat/conversations', { params })
export const createConversation = (body: ConversationCreate = {}) =>
  post<Conversation>('/chat/conversations', body)
export const getConversation = (id: string) => get<ConversationDetail>(`/chat/conversations/${id}`)
export const updateConversation = (id: string, body: ConversationUpdate) =>
  put<Conversation>(`/chat/conversations/${id}`, body)
export const deleteConversation = (id: string) => del<void>(`/chat/conversations/${id}`)

export const sendFeedback = (messageId: string, body: FeedbackBody) =>
  post<MessageFeedback>(`/chat/messages/${messageId}/feedback`, body)
export const requestKnowledge = (messageId: string, description?: string) =>
  post<KnowledgeGap>(`/chat/messages/${messageId}/knowledge-request`, {
    description: description || null,
  })
export const getCitationSource = (messageId: string, n: number) =>
  get<CitationSource>(`/chat/messages/${messageId}/citations/${n}`, { silent: true })

export interface AskHandlers {
  onMeta?: (data: ChatMetaEvent) => void
  onStep?: (data: ChatStep) => void
  onToken?: (text: string) => void
  onCitations?: (citations: Citation[]) => void
  onDone?: (data: ChatDoneEvent) => void
  onError?: (data: ChatErrorEvent) => void
}

export function dispatchChatEvent(event: SseEvent, handlers: AskHandlers): void {
  let data: unknown
  try {
    data = JSON.parse(event.data)
  } catch {
    return
  }
  switch (event.event) {
    case 'meta':
      handlers.onMeta?.(data as ChatMetaEvent)
      break
    case 'step':
      handlers.onStep?.(data as ChatStep)
      break
    case 'token':
      handlers.onToken?.((data as { text: string }).text)
      break
    case 'citations':
      handlers.onCitations?.((data as { citations: Citation[] }).citations)
      break
    case 'done':
      handlers.onDone?.(data as ChatDoneEvent)
      break
    case 'error':
      handlers.onError?.(data as ChatErrorEvent)
      break
  }
}

async function responseError(resp: Response): Promise<HttpError> {
  const data: unknown = await resp.json().catch(() => null)
  if (isApiErrorBody(data)) return new HttpError(resp.status, data)
  return new HttpError(resp.status, {
    code: `HTTP_${resp.status}`,
    message: `请求失败（${resp.status}）`,
    detail: data,
    trace_id: resp.headers.get('x-trace-id'),
  })
}

/**
 * Ask a question and consume the SSE answer stream. axios cannot stream response bodies
 * in the browser, so this uses fetch with the same bearer token.
 */
export async function askQuestion(
  conversationId: string,
  body: AskBody,
  handlers: AskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = await getValidToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    if (resp.status === 401) void login()
    throw await responseError(resp)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      dispatchChatEvent(event, handlers)
    }
  }
  for (const event of parser.push(decoder.decode())) dispatchChatEvent(event, handlers)
  for (const event of parser.flush()) dispatchChatEvent(event, handlers)
}
