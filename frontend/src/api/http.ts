import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import { getValidToken, login } from '@/auth/client'
import { currentLocale, t } from '@/i18n'
import type { ApiErrorBody } from './types'

declare module 'axios' {
  interface AxiosRequestConfig {
    /** Suppress the global error toast for this request. */
    silent?: boolean
  }
}

export class HttpError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown
  readonly traceId: string | null

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'HttpError'
    this.status = status
    this.code = body.code
    this.detail = body.detail
    this.traceId = body.trace_id
  }
}

export function isApiErrorBody(data: unknown): data is ApiErrorBody {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as ApiErrorBody).code === 'string' &&
    typeof (data as ApiErrorBody).message === 'string'
  )
}

export function toHttpError(error: unknown): HttpError {
  if (error instanceof AxiosError) {
    const status = error.response?.status ?? 0
    const data: unknown = error.response?.data
    if (isApiErrorBody(data)) {
      return new HttpError(status, data)
    }
    const traceId = (error.response?.headers?.['x-trace-id'] as string | undefined) ?? null
    if (!error.response) {
      const code = error.code === AxiosError.ECONNABORTED ? 'TIMEOUT' : 'NETWORK_ERROR'
      const message = code === 'TIMEOUT' ? t('layout.http.timeout') : t('layout.http.network')
      return new HttpError(0, { code, message, detail: null, trace_id: null })
    }
    return new HttpError(status, {
      code: `HTTP_${status}`,
      message: error.message || t('layout.http.failed', { status }),
      detail: data ?? null,
      trace_id: traceId,
    })
  }
  const message = error instanceof Error ? error.message : String(error)
  return new HttpError(0, { code: 'UNKNOWN', message, detail: null, trace_id: null })
}

function notify(err: HttpError): void {
  const suffix = err.traceId ? t('layout.http.trace', { id: err.traceId }) : ''
  ElMessage.error({ message: `${err.message}${suffix}`, grouping: true })
}

export async function attachAuthHeader(
  config: InternalAxiosRequestConfig,
): Promise<InternalAxiosRequestConfig> {
  const token = await getValidToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  config.headers.set('Accept-Language', currentLocale())
  return config
}

export function createHttp(baseURL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1') {
  const instance: AxiosInstance = axios.create({ baseURL, timeout: 30_000 })

  instance.interceptors.request.use(attachAuthHeader)

  instance.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      const err = toHttpError(error)
      const config = error instanceof AxiosError ? error.config : undefined
      if (err.status === 401) {
        void login()
      }
      if (!config?.silent) {
        notify(err)
      }
      return Promise.reject(err)
    },
  )

  return instance
}

export const http = createHttp()

export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return (await http.get<T>(url, config)).data
}

export async function post<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<T> {
  return (await http.post<T>(url, body, config)).data
}

export async function put<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<T> {
  return (await http.put<T>(url, body, config)).data
}

export async function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return (await http.delete<T>(url, config)).data
}
