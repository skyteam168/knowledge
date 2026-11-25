import { get, http, post } from './http'
import type {
  CanonicalEntity,
  CanonicalCreate,
  IdentifierCreate,
  IdentifierOut,
  Page,
  ResolveMatchIn,
  ResolveMatchOut,
} from './types'

const BASE = '/admin/structured/identity'

export const listCanonical = (params?: {
  page?: number
  size?: number
  object_type?: string
  status?: string
  q?: string
}) => get<Page<CanonicalEntity>>(`${BASE}/canonical`, { params })

export const createCanonical = (body: CanonicalCreate) =>
  post<CanonicalEntity>(`${BASE}/canonical`, body)

export const getCanonical = (id: string) => get<CanonicalEntity>(`${BASE}/canonical/${id}`)

export const addIdentifier = (canonicalId: string, body: IdentifierCreate) =>
  post<IdentifierOut>(`${BASE}/canonical/${canonicalId}/identifiers`, body)

export const deleteIdentifier = async (identifierId: string) => {
  await http.delete(`${BASE}/identifiers/${identifierId}`)
}

export const listIdentityConflicts = (params?: { page?: number; size?: number }) =>
  get<Page<CanonicalEntity>>(`${BASE}/conflicts`, { params })

export const resolveMatch = (body: ResolveMatchIn) =>
  post<ResolveMatchOut>(`${BASE}/resolve-match`, body)
