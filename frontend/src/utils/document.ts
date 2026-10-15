import type { AclPermission, KbDocument, PrincipalType } from '@/api/types'

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
      return { label: '排队中', type: 'info', progress: 10, active: true }
    case 'parsing':
      return { label: '解析中', type: 'primary', progress: 40, active: true }
    case 'parsed':
      return doc.chunk_count == null
        ? { label: '切分中', type: 'primary', progress: 70, active: true }
        : { label: '已切分', type: 'success', progress: 100, active: false }
    case 'indexing':
      return { label: '索引中', type: 'warning', progress: 85, active: true }
    case 'indexed':
      return { label: '已索引', type: 'success', progress: 100, active: false }
    case 'failed':
      return { label: '失败', type: 'danger', progress: 100, active: false }
  }
}

export const PERMISSION_LABELS: Record<AclPermission, string> = {
  read: '只读',
  edit: '编辑',
  manage: '管理',
}

export const PRINCIPAL_LABELS: Record<PrincipalType, string> = {
  dept: '部门',
  group: '用户组',
  role: '角色',
  user: '用户',
}

const LEVELS: Record<AclPermission, number> = { read: 1, edit: 2, manage: 3 }

export function atLeast(perm: AclPermission | null | undefined, required: AclPermission): boolean {
  return perm != null && LEVELS[perm] >= LEVELS[required]
}
