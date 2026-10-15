import { get, http, post, put } from './http'
import type {
  ClusterRunResult,
  DocumentAcl,
  DocumentAclUpdate,
  Gap,
  GapCluster,
  GapDetail,
  GapDraftBody,
  GapPatch,
  GapQuery,
  GapStats,
  KnowledgeObject,
  KnowledgeObjectDetail,
  KoCreate,
  KoQuery,
  KoType,
  KoUpdate,
  KoVersion,
  Notification,
  Page,
  PageParams,
  ReviewTask,
  ReviewTaskQuery,
} from './types'

const BASE = '/curation'
// FastAPI reads list params as repeated keys (status=a&status=b), not status[]=a.
const repeatedKeys = { indexes: null }
// LLM calls (drafts, FAQ batches, conflict judgements) can take a while.
const slow = { timeout: 180_000 }

// ---- gaps ---------------------------------------------------------------------------

export const listGaps = (params: GapQuery) =>
  get<Page<Gap>>(`${BASE}/gaps`, { params, paramsSerializer: repeatedKeys })
export const getGapStats = () => get<GapStats>(`${BASE}/gaps/stats`)
export const listGapClusters = (params: PageParams & { kb_id?: string; open_only?: boolean }) =>
  get<Page<GapCluster>>(`${BASE}/gap-clusters`, { params })
export const runGapClustering = () => post<ClusterRunResult>(`${BASE}/gap-clusters/run`, null, slow)
export const getGap = (id: string) => get<GapDetail>(`${BASE}/gaps/${id}`)
export const patchGap = async (id: string, body: GapPatch) =>
  (await http.patch<Gap>(`${BASE}/gaps/${id}`, body)).data
export const linkGapDocuments = (id: string, documentIds: string[], note?: string) =>
  post<Gap>(`${BASE}/gaps/${id}/link-documents`, { document_ids: documentIds, note: note || null })
export const rejectGap = (id: string, note?: string) =>
  post<Gap>(`${BASE}/gaps/${id}/reject`, { note: note || null })
export const markGapDuplicate = (id: string, duplicateOfId: string, note?: string) =>
  post<Gap>(`${BASE}/gaps/${id}/duplicate`, { duplicate_of_id: duplicateOfId, note: note || null })
export const reopenGap = (id: string) => post<Gap>(`${BASE}/gaps/${id}/reopen`)
export const draftFromGap = (id: string, body: GapDraftBody) =>
  post<KnowledgeObjectDetail>(`${BASE}/gaps/${id}/draft`, body, slow)

// ---- knowledge objects --------------------------------------------------------------

export const listKos = (params: KoQuery) => get<Page<KnowledgeObject>>(`${BASE}/kos`, { params })
export const createKo = (body: KoCreate) => post<KnowledgeObjectDetail>(`${BASE}/kos`, body)
export const getKo = (id: string) => get<KnowledgeObjectDetail>(`${BASE}/kos/${id}`)
export const updateKo = (id: string, body: KoUpdate) =>
  put<KnowledgeObjectDetail>(`${BASE}/kos/${id}`, body)
export const submitKo = (id: string, note?: string) =>
  post<KnowledgeObjectDetail>(`${BASE}/kos/${id}/submit`, { note: note || null }, slow)
export const withdrawKo = (id: string) => post<KnowledgeObjectDetail>(`${BASE}/kos/${id}/withdraw`)
export const reviewKo = (id: string, decision: 'approve' | 'reject', comment?: string) =>
  post<KnowledgeObjectDetail>(`${BASE}/kos/${id}/review`, { decision, comment: comment || null })
export const deprecateKo = (id: string, reason?: string) =>
  post<KnowledgeObjectDetail>(`${BASE}/kos/${id}/deprecate`, { reason: reason || null })
export const checkKoConflicts = (id: string) =>
  post<KnowledgeObjectDetail>(`${BASE}/kos/${id}/check-conflicts`, null, slow)
export const listKoVersions = (id: string) => get<KoVersion[]>(`${BASE}/kos/${id}/versions`)
export const getKoAcl = (id: string) => get<DocumentAcl>(`${BASE}/kos/${id}/acl`)
export const setKoAcl = (id: string, body: DocumentAclUpdate) =>
  put<DocumentAcl>(`${BASE}/kos/${id}/acl`, body)
export const generateFaq = (documentId: string, maxItems = 5, koType: KoType = 'faq') =>
  post<KnowledgeObject[]>(
    `${BASE}/documents/${documentId}/faq`,
    { max_items: maxItems, ko_type: koType },
    slow,
  )
export const listReviewTasks = (params: ReviewTaskQuery) =>
  get<Page<ReviewTask>>(`${BASE}/review-tasks`, { params })

// ---- notifications ------------------------------------------------------------------

export const listNotifications = (params: PageParams & { unread_only?: boolean }) =>
  get<Page<Notification>>('/notifications', { params })
export const getUnreadCount = () =>
  get<{ unread: number }>('/notifications/unread-count', { silent: true })
export const markNotificationsRead = (ids: string[] | null) =>
  post<{ unread: number }>('/notifications/read', { ids })
