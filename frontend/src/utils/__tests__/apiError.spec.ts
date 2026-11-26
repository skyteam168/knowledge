import { beforeEach, describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import { HttpError } from '@/api/http'
import { formatApiError, formatApiErrorToast } from '../apiError'
import { i18n, setLocale } from '@/i18n'

describe('formatApiError', () => {
  beforeEach(() => {
    setLocale('zh-CN')
    // Ensure the shared i18n instance is active for utils that call t/te.
    void createI18n
    void i18n
  })

  it('maps known English validation messages to Chinese', () => {
    const err = new HttpError(422, {
      code: 'VALIDATION_ERROR',
      message: 'object_type and external_id are required',
      detail: null,
      trace_id: 'abc',
    })
    const formatted = formatApiError(err)
    expect(formatted.message).toContain('对象类型')
    expect(formatted.message).toContain('外部编号')
    expect(formatted.traceId).toBe('abc')
  })

  it('maps MISSING_EXTERNAL_ID code', () => {
    const err = new HttpError(422, {
      code: 'MISSING_EXTERNAL_ID',
      message: 'external_id is required',
      detail: null,
      trace_id: null,
    })
    expect(formatApiError(err).message).toBe('请输入外部编号')
  })

  it('keeps already-localized Chinese messages', () => {
    const err = new HttpError(404, {
      code: 'NOT_FOUND',
      message: '文档不存在',
      detail: null,
      trace_id: null,
    })
    expect(formatApiError(err).message).toBe('文档不存在')
  })

  it('puts trace on a second toast line for support', () => {
    const err = new HttpError(422, {
      code: 'VALIDATION_ERROR',
      message: 'object_type and external_id are required',
      detail: null,
      trace_id: 'trace-9',
    })
    const toast = formatApiErrorToast(err)
    expect(toast).toContain('对象类型')
    expect(toast).toContain('trace-9')
    expect(toast).toContain('\n')
  })

  it('localizes to English when locale is en', () => {
    setLocale('en')
    const err = new HttpError(422, {
      code: 'MISSING_FIELDS',
      message: 'object_type and external_id are required',
      detail: null,
      trace_id: null,
    })
    expect(formatApiError(err).message.toLowerCase()).toContain('external')
  })
})
