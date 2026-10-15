import { del, get, post, put } from './http'
import type {
  ModelCheckResult,
  ModelInput,
  ModelItem,
  ModelKind,
  ModelOverview,
  ModelProvider,
  ModelProviderInput,
  ModelRoutesInput,
  ModelSyncResult,
  Page,
} from './types'

const BASE = '/admin/models'

export const getModelOverview = () => get<ModelOverview>(`${BASE}/overview`)
export const saveModelRoutes = (body: ModelRoutesInput) =>
  put<ModelOverview>(`${BASE}/routes`, body, { silent: true, timeout: 120_000 })

export const listModelProviders = () => get<ModelProvider[]>(`${BASE}/providers`)
export const createModelProvider = (body: ModelProviderInput) =>
  post<ModelProvider>(`${BASE}/providers`, body)
export const updateModelProvider = (id: string, body: ModelProviderInput) =>
  put<ModelProvider>(`${BASE}/providers/${id}`, body)
export const deleteModelProvider = (id: string) => del<void>(`${BASE}/providers/${id}`)
export const syncProviderModels = (id: string) =>
  post<ModelSyncResult>(`${BASE}/providers/${id}/sync`, undefined, { timeout: 60_000 })

export interface ModelListQuery {
  provider_id?: string
  kind?: ModelKind
  keyword?: string
  page?: number
  size?: number
}

export const listModels = (params: ModelListQuery) => get<Page<ModelItem>>(BASE, { params })
export const createModel = (body: ModelInput) => post<ModelItem>(BASE, body)
export const updateModel = (id: string, body: ModelInput) => put<ModelItem>(`${BASE}/${id}`, body)
export const deleteModel = (id: string) => del<void>(`${BASE}/${id}`)
export const checkModel = (id: string) =>
  post<ModelCheckResult>(`${BASE}/${id}/check`, undefined, { timeout: 60_000 })
