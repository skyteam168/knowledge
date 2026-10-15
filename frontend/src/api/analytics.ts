import { get, post } from './http'
import type {
  AnalyticsContent,
  AnalyticsFilters,
  AnalyticsOverview,
  AnalyticsQuery,
  AnalyticsRefreshResult,
  LlmUsage,
  LlmUsageQuery,
} from './types'

export const getAnalyticsFilters = (org_id?: string) =>
  get<AnalyticsFilters>('/analytics/filters', { params: { org_id } })
export const getAnalyticsOverview = (params: AnalyticsQuery) =>
  get<AnalyticsOverview>('/analytics/overview', { params })
export const getAnalyticsContent = (params: Pick<AnalyticsQuery, 'org_id' | 'kb_id'>) =>
  get<AnalyticsContent>('/analytics/content', { params })
export const getLlmUsage = (params: LlmUsageQuery) =>
  get<LlmUsage>('/analytics/llm-usage', { params })
export const refreshAnalytics = (days: number) =>
  post<AnalyticsRefreshResult>('/analytics/refresh', { days }, { timeout: 180_000 })
