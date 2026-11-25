import { get, http, post } from './http'
import type {
  ActionType,
  ActionTypeCreate,
  ActionTypeUpdate,
  OntologyRule,
  OntologyRuleCreate,
  OntologyRuleUpdate,
  SchemaImportIn,
  SchemaImportOut,
  SemanticAttribute,
  SemanticAttributeCreate,
  SemanticAttributeUpdate,
  SemanticBatchStatusIn,
  SemanticBatchStatusOut,
  SemanticEntity,
  SemanticEntityCreate,
  SemanticEvidence,
  SemanticEvidenceCreate,
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

export const rollbackSemanticVersion = (versionId: string) =>
  post<SemanticVersion>(`${BASE}/versions/${versionId}/rollback`)

export const importOntologySchema = (body: SchemaImportIn) =>
  post<SchemaImportOut>(`${BASE}/schema-import`, body)

export const suggestSemanticLabels = (versionId: string, dryRun = false) =>
  post<SemanticSuggestOut>(`${BASE}/versions/${versionId}/suggest`, undefined, {
    params: { dry_run: dryRun },
  })

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

export const listSemanticEvidences = (
  versionId: string,
  params?: { target_kind?: string; target_id?: string },
) => get<SemanticEvidence[]>(`${BASE}/versions/${versionId}/evidences`, { params })

export const addSemanticEvidence = (versionId: string, body: SemanticEvidenceCreate) =>
  post<SemanticEvidence>(`${BASE}/versions/${versionId}/evidences`, body)

export const deleteSemanticEvidence = async (evidenceId: string) => {
  await http.delete(`${BASE}/evidences/${evidenceId}`)
}

export const listOntologyRules = () => get<OntologyRule[]>(`${BASE}/rules`)

export const createOntologyRule = (body: OntologyRuleCreate) =>
  post<OntologyRule>(`${BASE}/rules`, body)

export const patchOntologyRule = async (ruleId: string, body: OntologyRuleUpdate) =>
  (await http.patch<OntologyRule>(`${BASE}/rules/${ruleId}`, body)).data

export const listActionTypes = (enabledOnly = false) =>
  get<ActionType[]>(`${BASE}/action-types`, { params: { enabled_only: enabledOnly } })

export const createActionType = (body: ActionTypeCreate) =>
  post<ActionType>(`${BASE}/action-types`, body)

export const patchActionType = async (actionId: string, body: ActionTypeUpdate) =>
  (await http.patch<ActionType>(`${BASE}/action-types/${actionId}`, body)).data
