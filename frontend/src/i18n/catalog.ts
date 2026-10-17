import { i18n, t } from './index'

const keyOf = (code: string): string => code.replace(/:/g, '_').replace(/\*/g, 'all')

/** Localized name of a built-in permission; unknown codes keep the backend name. */
export function permissionName(code: string, fallback: string): string {
  const key = `catalog.permission.${keyOf(code)}`
  return i18n.global.te(key, 'zh-CN') ? t(key) : fallback
}

/**
 * Localized name of a seeded system role. A role an admin has renamed keeps its custom name,
 * so only the untouched built-in name is translated.
 */
export function roleName(role: { code: string; name: string }): string {
  const key = `catalog.role.${keyOf(role.code)}`
  if (!i18n.global.te(key, 'zh-CN')) return role.name
  return role.name === i18n.global.t(key, {}, { locale: 'zh-CN' }) ? t(key) : role.name
}
