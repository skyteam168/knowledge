import axios, { type AxiosProgressEvent } from 'axios'
import { del, get, http, post, put } from './http'
import type {
  Chunk,
  DirectoryDepartment,
  DocumentAcl,
  DocumentAclUpdate,
  DocumentContent,
  DocumentDetail,
  DocumentLifecycleIn,
  DocumentQuery,
  DocumentStatus,
  DocumentUpdate,
  KbAcl,
  KbAclUpdate,
  KbDocument,
  KnowledgeBase,
  KnowledgeBaseCreate,
  KnowledgeBaseUpdate,
  Page,
  PageParams,
  Preview,
  PrincipalOption,
  PrincipalType,
  UploadInit,
  UploadInitResult,
  UploadResult,
  VersionCompare,
  VersionText,
} from './types'

// ---- knowledge bases ------------------------------------------------------------

export const listKnowledgeBases = (params: PageParams & { keyword?: string }) =>
  get<Page<KnowledgeBase>>('/knowledge-bases', { params })
export const getKnowledgeBase = (id: string) => get<KnowledgeBase>(`/knowledge-bases/${id}`)
export const createKnowledgeBase = (body: KnowledgeBaseCreate) =>
  post<KnowledgeBase>('/knowledge-bases', body)
export const updateKnowledgeBase = (id: string, body: KnowledgeBaseUpdate) =>
  put<KnowledgeBase>(`/knowledge-bases/${id}`, body)
export const deleteKnowledgeBase = (id: string) => del<void>(`/knowledge-bases/${id}`)
export const getKnowledgeBaseAcl = (id: string) => get<KbAcl>(`/knowledge-bases/${id}/acl`)
export const setKnowledgeBaseAcl = (id: string, body: KbAclUpdate) =>
  put<KbAcl>(`/knowledge-bases/${id}/acl`, body)

// ---- documents ----------------------------------------------------------------------

export const listDocuments = (kbId: string, params: DocumentQuery) =>
  get<Page<KbDocument>>(`/knowledge-bases/${kbId}/documents`, { params })
export const createUpload = (kbId: string, body: UploadInit) =>
  post<UploadInitResult>(`/knowledge-bases/${kbId}/documents/upload-url`, body, { silent: true })
export const completeUpload = (kbId: string, ticket: string, tags: string[] = []) =>
  post<UploadResult>(
    `/knowledge-bases/${kbId}/documents/complete`,
    { ticket, tags },
    { silent: true, timeout: 0 },
  )

/** Fallback when the browser cannot hash files (non-secure context): upload via the API. */
export async function uploadDirect(
  kbId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const resp = await http.post<UploadResult>(`/knowledge-bases/${kbId}/documents`, form, {
    silent: true,
    timeout: 0,
    onUploadProgress: (e: AxiosProgressEvent) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
  return resp.data
}
export const getDocument = (id: string) => get<DocumentDetail>(`/documents/${id}`)
export const updateDocument = (id: string, body: DocumentUpdate) =>
  put<KbDocument>(`/documents/${id}`, body)
export const deleteDocument = (id: string) => del<void>(`/documents/${id}`)
export const reprocessDocument = (id: string) => post<KbDocument>(`/documents/${id}/reprocess`)
export const batchReprocessDocuments = (
  kbId: string,
  body: {
    document_ids?: string[]
    status?: DocumentStatus
    missing_page_images?: boolean
    limit?: number
  },
) =>
  post<{
    queued: string[]
    skipped: { id: string; reason: string }[]
    total_candidates: number
  }>(`/knowledge-bases/${kbId}/documents/reprocess`, body)
export const createMarkdownDocument = (
  kbId: string,
  body: { title: string; content: string; tags?: string[] },
) => post<UploadResult>(`/knowledge-bases/${kbId}/documents/markdown`, body, { silent: true })
export const getDocumentContent = (id: string) => get<DocumentContent>(`/documents/${id}/content`)
/** Read-only Markdown / text body for rendered preview (requires kb:read only). */
export const getDocumentPreviewText = (id: string) =>
  get<DocumentContent>(`/documents/${id}/preview-text`)
export const saveDocumentContent = (id: string, content: string, baseVersion: number) =>
  put<UploadResult>(
    `/documents/${id}/content`,
    { content, base_version: baseVersion },
    { silent: true },
  )
export const reviewDocument = (id: string, note?: string) =>
  post<KbDocument>(`/documents/${id}/review`, { note: note || null })
export const transitionDocumentLifecycle = (id: string, body: DocumentLifecycleIn) =>
  post<KbDocument>(`/documents/${id}/lifecycle`, body)
export const listChunks = (id: string) => get<Chunk[]>(`/documents/${id}/chunks`)
export const getPreviewUrl = (id: string) => get<Preview>(`/documents/${id}/preview-url`)
export const getDownloadUrl = (id: string) => get<Preview>(`/documents/${id}/download-url`)
export const getVersionPreviewUrl = (id: string, version: number) =>
  get<Preview>(`/documents/${id}/versions/${version}/preview-url`)
export const getVersionDownloadUrl = (id: string, version: number) =>
  get<Preview>(`/documents/${id}/versions/${version}/download-url`)
export const getVersionText = (id: string, version: number) =>
  get<VersionText>(`/documents/${id}/versions/${version}/text`)
export const compareVersions = (id: string, base: number, target: number) =>
  get<VersionCompare>(`/documents/${id}/versions/compare`, { params: { base, target } })
export const restoreVersion = (id: string, version: number) =>
  post<KbDocument>(`/documents/${id}/versions/${version}/restore`)
export const getDocumentAcl = (id: string) => get<DocumentAcl>(`/documents/${id}/acl`)
export const setDocumentAcl = (id: string, body: DocumentAclUpdate) =>
  put<DocumentAcl>(`/documents/${id}/acl`, body)

/** PUT the file straight to object storage via the presigned URL (no auth header). */
export async function putToStorage(
  url: string,
  file: Blob,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  await axios.put(url, file, {
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    signal,
    timeout: 0,
    onUploadProgress: (e: AxiosProgressEvent) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

// ---- directory (permission pickers) ----------------------------------------------

export const getDirectoryDepartments = () => get<DirectoryDepartment[]>('/directory/departments')
export const searchPrincipals = (type: PrincipalType, keyword?: string) =>
  get<PrincipalOption[]>('/directory/principals', { params: { type, keyword, limit: 30 } })
