import { del, get, http, post } from './http'
import type {
  Page,
  PageParams,
  TerminologyAlias,
  TerminologyAliasCreate,
  TerminologyEntity,
  TerminologyEntityCreate,
  TerminologyEntityUpdate,
  TerminologyNeighborhood,
} from './types'

const BASE = '/admin/terminology'

export const listTerminologyEntities = (
  params: PageParams & { q?: string; entity_type?: string; status?: string },
) => get<Page<TerminologyEntity>>(`${BASE}/entities`, { params })

export const getTerminologyEntity = (id: string) =>
  get<TerminologyEntity>(`${BASE}/entities/${id}`)

export const getTerminologyNeighborhood = (id: string) =>
  get<TerminologyNeighborhood>(`${BASE}/entities/${id}/neighborhood`)

export const createTerminologyEntity = (body: TerminologyEntityCreate) =>
  post<TerminologyEntity>(`${BASE}/entities`, body)

export const updateTerminologyEntity = async (id: string, body: TerminologyEntityUpdate) =>
  (await http.patch<TerminologyEntity>(`${BASE}/entities/${id}`, body)).data

export const deleteTerminologyEntity = (id: string) => del<void>(`${BASE}/entities/${id}`)

export const addTerminologyAlias = (entityId: string, body: TerminologyAliasCreate) =>
  post<TerminologyAlias>(`${BASE}/entities/${entityId}/aliases`, body)

export const deleteTerminologyAlias = (aliasId: string) =>
  del<void>(`${BASE}/aliases/${aliasId}`)

export const syncTerminologySynonyms = (reload = true) =>
  post<{ path: string; lines: number; reloaded: boolean }>(`${BASE}/synonyms/sync`, undefined, {
    params: { reload },
  })
