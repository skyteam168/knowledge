import { te, t } from '@/i18n'
import type { HttpError } from '@/api/http'

export type FormattedApiError = {
  /** User-facing, localized. */
  message: string
  /** Stable machine code from API when present. */
  code: string
  /** For ops / support; omit from primary toast when possible. */
  traceId: string | null
}

/** Exact English backend messages → i18n keys (extend as needed). */
const MESSAGE_KEYS: Record<string, string> = {
  'object_type and external_id are required': 'layout.apiMessages.objectTypeExternalIdRequired',
  'object_type is required': 'structured.objectTypeRequired',
  'external_id is required': 'structured.externalIdRequired',
  'Request validation failed': 'layout.apiMessages.requestValidationFailed',
  'Validation failed': 'layout.apiMessages.requestValidationFailed',
  'Resource not found': 'layout.apiMessages.notFound',
  'Permission denied': 'layout.apiMessages.permissionDenied',
  'Authentication required': 'layout.apiMessages.unauthorized',
  'Internal server error': 'layout.apiMessages.internal',
  'Device not found': 'layout.apiMessages.deviceNotFound',
  'Work order not found': 'layout.apiMessages.workOrderNotFound',
  'Spare part not found': 'layout.apiMessages.sparePartNotFound',
  'Structured record not found': 'layout.apiMessages.structuredRecordNotFound',
  'Structured source not found': 'layout.apiMessages.sourceNotFound',
  'Domain not found': 'layout.apiMessages.domainNotFound',
  'Bad request': 'layout.apiMessages.badRequest',
}

const CODE_KEYS: Record<string, string> = {
  VALIDATION_ERROR: 'layout.errors.VALIDATION_ERROR',
  NOT_FOUND: 'layout.errors.NOT_FOUND',
  PERMISSION_DENIED: 'layout.errors.PERMISSION_DENIED',
  UNAUTHORIZED: 'layout.errors.UNAUTHORIZED',
  CONFLICT: 'layout.errors.CONFLICT',
  INTERNAL_ERROR: 'layout.errors.INTERNAL_ERROR',
  BAD_REQUEST: 'layout.errors.BAD_REQUEST',
  TIMEOUT: 'layout.http.timeout',
  NETWORK_ERROR: 'layout.http.network',
  MISSING_EXTERNAL_ID: 'structured.externalIdRequired',
  MISSING_OBJECT_TYPE: 'structured.objectTypeRequired',
  MISSING_FIELDS: 'layout.apiMessages.objectTypeExternalIdRequired',
  DEVICE_NOT_FOUND: 'layout.apiMessages.deviceNotFound',
  WORK_ORDER_NOT_FOUND: 'layout.apiMessages.workOrderNotFound',
  SPARE_PART_NOT_FOUND: 'layout.apiMessages.sparePartNotFound',
  STRUCTURED_RECORD_NOT_FOUND: 'layout.apiMessages.structuredRecordNotFound',
}

function looksUserLocalized(message: string): boolean {
  // CJK / Vietnamese-ish diacritics → treat as already localized.
  return /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u00C0-\u024F]/.test(message)
}

function translateIfExists(key: string): string | null {
  if (!te(key)) return null
  return t(key)
}

/**
 * Map API / HttpError into a short user-facing message.
 * Trace ids stay available for ops but are not the primary toast text.
 */
export function formatApiError(err: HttpError): FormattedApiError {
  const code = err.code || 'UNKNOWN'
  const raw = (err.message || '').trim()

  const byMessage = raw ? MESSAGE_KEYS[raw] : undefined
  if (byMessage) {
    const translated = translateIfExists(byMessage)
    if (translated) {
      return { message: translated, code, traceId: err.traceId }
    }
  }

  const byCode = CODE_KEYS[code]
  if (byCode) {
    const translated = translateIfExists(byCode)
    if (translated) {
      // Prefer specific mapped English messages over generic code text when both exist.
      if (raw && looksUserLocalized(raw)) {
        return { message: raw, code, traceId: err.traceId }
      }
      if (!byMessage) {
        return { message: translated, code, traceId: err.traceId }
      }
    }
  }

  if (raw && looksUserLocalized(raw)) {
    return { message: raw, code, traceId: err.traceId }
  }

  if (raw && MESSAGE_KEYS[raw]) {
    const translated = translateIfExists(MESSAGE_KEYS[raw])
    if (translated) return { message: translated, code, traceId: err.traceId }
  }

  // Connector / seed sync strings (prefix match)
  if (/no connector in meta/i.test(raw) || /Seed\/manual source cannot sync/i.test(raw)) {
    const translated = translateIfExists('layout.apiMessages.sourceNoConnector')
    if (translated) return { message: translated, code, traceId: err.traceId }
  }

  if (err.status === 404) {
    return {
      message: translateIfExists('layout.errors.NOT_FOUND') ?? t('layout.apiMessages.notFound'),
      code,
      traceId: err.traceId,
    }
  }
  if (err.status === 403) {
    return {
      message:
        translateIfExists('layout.errors.PERMISSION_DENIED') ??
        t('layout.apiMessages.permissionDenied'),
      code,
      traceId: err.traceId,
    }
  }
  if (err.status >= 500) {
    return {
      message: translateIfExists('layout.errors.INTERNAL_ERROR') ?? t('layout.apiMessages.internal'),
      code,
      traceId: err.traceId,
    }
  }

  return {
    message: translateIfExists('layout.errors.generic') ?? t('layout.http.failed', { status: err.status || '—' }),
    code,
    traceId: err.traceId,
  }
}

/** Toast text: user message + optional support trace on a second line. */
export function formatApiErrorToast(err: HttpError): string {
  const formatted = formatApiError(err)
  if (!formatted.traceId) return formatted.message
  return `${formatted.message}\n${t('layout.http.traceHint', { id: formatted.traceId })}`
}
