import { del, get, http, post } from './http'
import type {
  EvalCandidate,
  EvalCandidateQuery,
  EvalCase,
  EvalCaseFields,
  EvalCompare,
  EvalDataset,
  EvalDatasetCreate,
  EvalImportResult,
  EvalImportSource,
  EvalResult,
  EvalRun,
  EvalRunCreate,
  Page,
  PageParams,
} from './types'

const BASE = '/evaluation'

export const listEvalDatasets = (params: PageParams) =>
  get<Page<EvalDataset>>(`${BASE}/datasets`, { params })
export const getEvalDataset = (id: string) => get<EvalDataset>(`${BASE}/datasets/${id}`)
export const createEvalDataset = (body: EvalDatasetCreate) =>
  post<EvalDataset>(`${BASE}/datasets`, body)
export const updateEvalDataset = async (id: string, body: Partial<EvalDatasetCreate>) =>
  (await http.patch<EvalDataset>(`${BASE}/datasets/${id}`, body)).data
export const deleteEvalDataset = (id: string) => del<void>(`${BASE}/datasets/${id}`)

export const listEvalCases = (datasetId: string, params: PageParams & { keyword?: string }) =>
  get<Page<EvalCase>>(`${BASE}/datasets/${datasetId}/cases`, { params })
export const createEvalCase = (datasetId: string, body: EvalCaseFields) =>
  post<EvalCase>(`${BASE}/datasets/${datasetId}/cases`, body)
export const updateEvalCase = async (id: string, body: Partial<EvalCaseFields>) =>
  (await http.patch<EvalCase>(`${BASE}/cases/${id}`, body)).data
export const deleteEvalCase = (id: string) => del<void>(`${BASE}/cases/${id}`)

export const listEvalCandidates = (params: EvalCandidateQuery) =>
  get<Page<EvalCandidate>>(`${BASE}/candidates`, { params })
export const importEvalCases = (
  datasetId: string,
  source: EvalImportSource,
  source_ids: string[],
) => post<EvalImportResult>(`${BASE}/datasets/${datasetId}/import`, { source, source_ids })

export const listEvalRuns = (params: PageParams & { dataset_id?: string }) =>
  get<Page<EvalRun>>(`${BASE}/runs`, { params })
export const createEvalRun = (body: EvalRunCreate) => post<EvalRun>(`${BASE}/runs`, body)
export const getEvalRun = (id: string) => get<EvalRun>(`${BASE}/runs/${id}`)
export const deleteEvalRun = (id: string) => del<void>(`${BASE}/runs/${id}`)
export const listEvalResults = (runId: string, params: PageParams & { only_failed?: boolean }) =>
  get<Page<EvalResult>>(`${BASE}/runs/${runId}/results`, { params })
export const compareEvalRuns = (runIds: string[]) =>
  get<EvalCompare>(`${BASE}/runs/compare`, {
    params: { run_ids: runIds },
    paramsSerializer: { indexes: null },
  })
