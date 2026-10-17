import type { ApiPrincipalType, ApiScope } from '@/api/types'
import { t } from '@/i18n'

export const SCOPES: readonly ApiScope[] = ['retrieve', 'chat', 'mcp']

export function scopeLabel(scope: ApiScope): string {
  return t(`openApi.scopes.${scope}.label`)
}

export function scopeDesc(scope: ApiScope): string {
  return t(`openApi.scopes.${scope}.desc`)
}

export function principalLabel(type: ApiPrincipalType): string {
  return t(`openApi.principals.${type}`)
}

export function openApiBase(): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
  return new URL(`${base}/open`, window.location.origin).toString()
}
