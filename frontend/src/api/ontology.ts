import { get, http, post } from './http'
import type {
  SchemaImportIn,
  SchemaImportOut,
  SemanticAttribute,
  SemanticAttributeCreate,
  SemanticAttributeUpdate,
  SemanticBatchStatusIn,
  SemanticBatchStatusOut,
  SemanticEntity,
  SemanticEntityCreate,
  SemanticItemStatus,
  SemanticMapping,
  SemanticMappingCreate,
  SemanticSuggestOut,
  SemanticVersion,
  SemanticVersionCreate,
  SemanticVersionDetail,
} from './types'

const BASE = '/admin/ontology'

export const listSemanticVersions = () => get<SemanticVersion[]>(`${BASE}/versions`)

export const createSemanticVersion = (body: SemanticVersionCreate) =>
  post<SemanticVersion>(`${BASE}/versions`, body)

export const getSemanticVersion = (versionId: string) =>
  get<SemanticVersionDetail>(`${BASE}/versions/${versionId}`)

export const getPublishedSemanticVersion = () =>
  get<SemanticVersionDetail | null>(`${BASE}/published`)

export const publishSemanticVersion = (versionId: string) =>
  post<SemanticVersion>(`${BASE}/versions/${versionId}/publish`)

export const importOntologySchema = (body: SchemaImportIn) =>
  post<SchemaImportOut>(`${BASE}/schema-import`, body)

export const suggestSemanticLabels = (versionId: string) =>
  post<SemanticSuggestOut>(`${BASE}/versions/${versionId}/suggest`)

export const batchSetSemanticStatus = (versionId: string, body: SemanticBatchStatusIn) =>
  post<SemanticBatchStatusOut>(`${BASE}/versions/${versionId}/batch-status`, body)

export const addSemanticEntity = (versionId: string, body: SemanticEntityCreate) =>
  post<SemanticEntity>(`${BASE}/versions/${versionId}/entities`, body)

export const setSemanticEntityStatus = async (entityId: string, status: SemanticItemStatus) =>
  (await http.patch<SemanticEntity>(`${BASE}/entities/${entityId}/status`, { status })).data

export const addSemanticAttribute = (entityId: string, body: SemanticAttributeCreate) =>
  post<SemanticAttribute>(`${BASE}/entities/${entityId}/attributes`, body)

export const updateSemanticAttribute = async (
  attributeId: string,
  body: SemanticAttributeUpdate,
) => (await http.patch<SemanticAttribute>(`${BASE}/attributes/${attributeId}`, body)).data

export const setSemanticAttributeStatus = async (
  attributeId: string,
  status: SemanticItemStatus,
) =>
  (await http.patch<SemanticAttribute>(`${BASE}/attributes/${attributeId}/status`, { status }))
    .data

export const addSemanticMapping = (attributeId: string, body: SemanticMappingCreate) =>
  post<SemanticMapping>(`${BASE}/attributes/${attributeId}/mappings`, body)

export const setSemanticMappingStatus = async (mappingId: string, status: SemanticItemStatus) =>
  (await http.patch<SemanticMapping>(`${BASE}/mappings/${mappingId}/status`, { status })).data
