import { del, get, post, put } from './http'
import type {
  ApiCallLog,
  ApiClient,
  ApiClientBody,
  ApiClientStatus,
  ApiClientUpdate,
  ApiKey,
  ApiKeyCreated,
  ApiUsage,
  OpenApiOptions,
  OpenRetrieveResult,
  Page,
  PageParams,
} from './types'

const BASE = '/admin/open-api'

export const getOpenApiOptions = () => get<OpenApiOptions>(`${BASE}/options`)

export const listApiClients = (
  params: PageParams & { keyword?: string; status?: ApiClientStatus },
) => get<Page<ApiClient>>(`${BASE}/clients`, { params })
export const getApiClient = (id: string) => get<ApiClient>(`${BASE}/clients/${id}`)
export const createApiClient = (body: ApiClientBody) => post<ApiClient>(`${BASE}/clients`, body)
export const updateApiClient = (id: string, body: ApiClientUpdate) =>
  put<ApiClient>(`${BASE}/clients/${id}`, body)
export const deleteApiClient = (id: string) => del<void>(`${BASE}/clients/${id}`)

export const listApiKeys = (clientId: string) => get<ApiKey[]>(`${BASE}/clients/${clientId}/keys`)
export const createApiKey = (
  clientId: string,
  body: { name: string; expires_at?: string | null },
) => post<ApiKeyCreated>(`${BASE}/clients/${clientId}/keys`, body)
export const revokeApiKey = (clientId: string, keyId: string) =>
  post<ApiKey>(`${BASE}/clients/${clientId}/keys/${keyId}/revoke`)

export const listApiCallLogs = (
  clientId: string,
  params: PageParams & { outcome?: 'ok' | 'error' },
) => get<Page<ApiCallLog>>(`${BASE}/clients/${clientId}/logs`, { params })
export const getApiUsage = (clientId: string, days = 14) =>
  get<ApiUsage>(`${BASE}/clients/${clientId}/usage`, { params: { days } })

export const previewApiClient = (
  clientId: string,
  body: { query: string; kb_ids?: string[]; top_k?: number },
) => post<OpenRetrieveResult>(`${BASE}/clients/${clientId}/preview`, body)
