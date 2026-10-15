import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { attachAuthHeader, createHttp, HttpError, toHttpError } from '../http'
import { getValidToken, login } from '@/auth/client'

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }))
vi.mock('@/auth/client', () => ({
  getValidToken: vi.fn(),
  login: vi.fn().mockResolvedValue(undefined),
}))

function makeConfig(): InternalAxiosRequestConfig {
  return { headers: new AxiosHeaders() } as InternalAxiosRequestConfig
}

describe('http', () => {
  beforeEach(() => {
    vi.mocked(getValidToken).mockReset()
    vi.mocked(login).mockClear()
  })

  it('injects a fresh bearer token when logged in', async () => {
    vi.mocked(getValidToken).mockResolvedValue('tok-1')
    const config = await attachAuthHeader(makeConfig())
    expect(config.headers.get('Authorization')).toBe('Bearer tok-1')
  })

  it('does not inject header without token', async () => {
    vi.mocked(getValidToken).mockResolvedValue(undefined)
    const config = await attachAuthHeader(makeConfig())
    expect(config.headers.has('Authorization')).toBe(false)
  })

  it('maps backend error body to HttpError', () => {
    const config = makeConfig()
    const err = new AxiosError('fail', 'ERR_BAD_REQUEST', config, null, {
      status: 404,
      statusText: 'Not Found',
      headers: {},
      config,
      data: { code: 'NOT_FOUND', message: '文档不存在', detail: null, trace_id: 't-1' },
    })
    const httpErr = toHttpError(err)
    expect(httpErr).toBeInstanceOf(HttpError)
    expect(httpErr.status).toBe(404)
    expect(httpErr.code).toBe('NOT_FOUND')
    expect(httpErr.message).toBe('文档不存在')
    expect(httpErr.traceId).toBe('t-1')
  })

  it('maps network errors', () => {
    const err = new AxiosError('Network Error', 'ERR_NETWORK', makeConfig())
    expect(toHttpError(err).code).toBe('NETWORK_ERROR')
  })

  it('redirects to login on 401 and rejects with HttpError', async () => {
    vi.mocked(getValidToken).mockResolvedValue('expired')
    const http = createHttp('/api/v1')
    http.defaults.adapter = (config) =>
      Promise.reject(
        new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, {
          status: 401,
          statusText: 'Unauthorized',
          headers: {},
          config,
          data: { code: 'UNAUTHORIZED', message: '请登录', detail: null, trace_id: null },
        }),
      )
    await expect(http.get('/me', { silent: true })).rejects.toMatchObject({
      status: 401,
      code: 'UNAUTHORIZED',
    })
    expect(login).toHaveBeenCalledOnce()
  })

  it('does not redirect on 403', async () => {
    vi.mocked(getValidToken).mockResolvedValue('tok')
    const http = createHttp('/api/v1')
    http.defaults.adapter = (config) =>
      Promise.reject(
        new AxiosError('Forbidden', 'ERR_BAD_REQUEST', config, null, {
          status: 403,
          statusText: 'Forbidden',
          headers: {},
          config,
          data: { code: 'PERMISSION_DENIED', message: '无权限', detail: null, trace_id: null },
        }),
      )
    await expect(http.get('/admin/users', { silent: true })).rejects.toMatchObject({
      status: 403,
    })
    expect(login).not.toHaveBeenCalled()
  })
})
