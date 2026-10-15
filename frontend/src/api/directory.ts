import { del, get, http, post, put } from './http'
import type {
  DirectorySource,
  DirectorySourceBody,
  DirectorySourceType,
  DirectorySourceUpdate,
  DirectoryTestResult,
  Page,
  PageParams,
  SyncMode,
  SyncRun,
  SyncRunDetail,
} from './types'

const BASE = '/admin/directory'

export const listDirectorySources = () => get<DirectorySource[]>(`${BASE}/sources`)
export const createDirectorySource = (body: DirectorySourceBody) =>
  post<DirectorySource>(`${BASE}/sources`, body)
export const updateDirectorySource = (id: string, body: DirectorySourceUpdate) =>
  put<DirectorySource>(`${BASE}/sources/${id}`, body)
export const deleteDirectorySource = (id: string) => del<void>(`${BASE}/sources/${id}`)

export const testDirectorySource = (body: {
  type: DirectorySourceType
  config: Record<string, unknown>
  source_id?: string
}) => post<DirectoryTestResult>(`${BASE}/test`, body, { timeout: 180_000 })

export const startDirectorySync = (id: string, mode: SyncMode, force = false) =>
  post<SyncRun>(`${BASE}/sources/${id}/sync`, { mode, force })

export async function uploadDirectoryExcel(
  id: string,
  file: File,
  mode: SyncMode,
  force = false,
): Promise<SyncRunDetail> {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)
  form.append('force', String(force))
  return post<SyncRunDetail>(`${BASE}/sources/${id}/upload`, form, { timeout: 300_000 })
}

export const listSyncRuns = (params: PageParams & { source_id?: string }) =>
  get<Page<SyncRun>>(`${BASE}/runs`, { params })
export const getSyncRun = (id: string) => get<SyncRunDetail>(`${BASE}/runs/${id}`)

export async function downloadExcelTemplate(): Promise<void> {
  const resp = await http.get<Blob>(`${BASE}/excel-template`, { responseType: 'blob' })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = '组织架构导入模板.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}
