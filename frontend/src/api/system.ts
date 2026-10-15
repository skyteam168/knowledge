import { get } from './http'
import type { HealthResponse, ReadinessResponse } from './types'

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>('/health', { baseURL: '/', silent: true })
}

export function fetchReadiness(): Promise<ReadinessResponse> {
  return get<ReadinessResponse>('/ready', {
    baseURL: '/',
    silent: true,
    validateStatus: (status) => status === 200 || status === 503,
  })
}
