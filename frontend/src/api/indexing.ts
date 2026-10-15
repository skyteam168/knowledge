import { get, post } from './http'
import type {
  ConsistencyReport,
  IndexGeneration,
  OutboxEvent,
  OutboxQuery,
  OutboxStats,
  Page,
  RepairQueued,
  RetryResult,
} from './types'

export const getOutboxStats = () => get<OutboxStats>('/admin/index/outbox/stats')
export const listOutboxEvents = (params: OutboxQuery) =>
  get<Page<OutboxEvent>>('/admin/index/outbox', { params })
export const retryOutboxEvent = (id: string) => post<OutboxEvent>(`/admin/index/outbox/${id}/retry`)
export const retryDeadEvents = () => post<RetryResult>('/admin/index/outbox/retry-dead')

export const listGenerations = () => get<IndexGeneration[]>('/admin/index/generations')

export const checkKbConsistency = (kbId: string) =>
  post<ConsistencyReport>(`/admin/index/kbs/${kbId}/check`, undefined, { timeout: 180_000 })
export const repairKbIndex = (kbId: string) => post<RepairQueued>(`/admin/index/kbs/${kbId}/repair`)

export const reloadSynonyms = () => post<void>('/admin/index/synonyms/reload')
