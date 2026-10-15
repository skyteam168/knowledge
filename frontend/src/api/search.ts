import { del, get, post, put } from './http'
import type {
  Page,
  RetrievalConfig,
  RetrievalProfile,
  RetrievalProfileCreate,
  RetrievalProfileUpdate,
  RetrievalTrace,
  RetrievalTraceQuery,
  RetrievalTraceSummary,
  SearchOptions,
  SearchQuery,
  SearchResponse,
} from './types'

// FastAPI reads list params as repeated keys (kb_ids=a&kb_ids=b), not kb_ids[]=a.
const repeatedKeys = { indexes: null }

export const search = (params: SearchQuery) =>
  get<SearchResponse>('/search', { params, paramsSerializer: repeatedKeys })
export const getSearchOptions = () => get<SearchOptions>('/search/options')

const ADMIN = '/admin/retrieval'

export const listRetrievalProfiles = () => get<RetrievalProfile[]>(`${ADMIN}/profiles`)
export const getDefaultRetrievalConfig = () => get<RetrievalConfig>(`${ADMIN}/profiles/defaults`)
export const createRetrievalProfile = (body: RetrievalProfileCreate) =>
  post<RetrievalProfile>(`${ADMIN}/profiles`, body)
export const updateRetrievalProfile = (id: string, body: RetrievalProfileUpdate) =>
  put<RetrievalProfile>(`${ADMIN}/profiles/${id}`, body)
export const deleteRetrievalProfile = (id: string) => del<void>(`${ADMIN}/profiles/${id}`)
/** `id` = 'builtin' reverts to the built-in defaults. */
export const activateRetrievalProfile = (id: string) =>
  post<RetrievalProfile>(`${ADMIN}/profiles/${id}/activate`)

export const listRetrievalTraces = (params: RetrievalTraceQuery) =>
  get<Page<RetrievalTraceSummary>>(`${ADMIN}/traces`, { params })
export const getRetrievalTrace = (id: string) => get<RetrievalTrace>(`${ADMIN}/traces/${id}`)
