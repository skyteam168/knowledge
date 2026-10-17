import type { AclPermission, KbDocument, PrincipalType } from '@/api/types'
import { t } from '@/i18n'

export type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface StatusView {
  label: string
  type: TagType
  progress: number
  /** Still moving through the pipeline: worth polling. */
  active: boolean
}

export function documentStatus(doc: Pick<KbDocument, 'status' | 'chunk_count'>): StatusView {
  switch (doc.status) {
    case 'uploaded':
      return { label: t('knowledge.docStatus.queued'), type: 'info', progress: 10, active: true }
    case 'parsing':
      return {
        label: t('knowledge.docStatus.parsing'),
        type: 'primary',
        progress: 40,
        active: true,
      }
    case 'parsed':
      return doc.chunk_count == null
        ? { label: t('knowledge.docStatus.chunking'), type: 'primary', progress: 70, active: true }
        : { label: t('knowledge.docStatus.chunked'), type: 'success', progress: 100, active: false }
    case 'indexing':
      return {
        label: t('knowledge.docStatus.indexing'),
        type: 'warning',
        progress: 85,
        active: true,
      }
    case 'indexed':
      return {
        label: t('knowledge.docStatus.indexed'),
        type: 'success',
        progress: 100,
        active: false,
      }
    case 'failed':
      return {
        label: t('knowledge.docStatus.failed'),
        type: 'danger',
        progress: 100,
        active: false,
      }
  }
}

const PERMISSIONS: AclPermission[] = ['read', 'edit', 'manage']
const PRINCIPALS: PrincipalType[] = ['dept', 'group', 'role', 'user']

export function permissionLabel(permission: AclPermission): string {
  return t(`knowledge.permission.${permission}`)
}

/** Ordered `{ permission: label }` in the current locale. */
export function permissionLabels(): Record<AclPermission, string> {
  return Object.fromEntries(PERMISSIONS.map((p) => [p, permissionLabel(p)])) as Record<
    AclPermission,
    string
  >
}

export function principalLabel(type: PrincipalType): string {
  return t(`knowledge.principal.${type}`)
}

/** Ordered `{ principal type: label }` in the current locale. */
export function principalLabels(): Record<PrincipalType, string> {
  return Object.fromEntries(PRINCIPALS.map((p) => [p, principalLabel(p)])) as Record<
    PrincipalType,
    string
  >
}

const LEVELS: Record<AclPermission, number> = { read: 1, edit: 2, manage: 3 }

export function atLeast(perm: AclPermission | null | undefined, required: AclPermission): boolean {
  return perm != null && LEVELS[perm] >= LEVELS[required]
}
