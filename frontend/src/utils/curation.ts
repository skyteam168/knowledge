import type {
  ConflictVerdict,
  GapStatus,
  GapType,
  KoStatus,
  KoType,
  KoVersionStatus,
  ReviewStatus,
} from '@/api/types'

export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

interface Meta {
  label: string
  type: TagType
}

export const GAP_TYPE_META: Record<GapType, Meta> = {
  no_evidence: { label: '无依据', type: 'danger' },
  low_grounding: { label: '依据不足', type: 'warning' },
  negative_feedback: { label: '用户差评', type: 'warning' },
  user_request: { label: '用户求助', type: 'primary' },
}

export const GAP_STATUS_META: Record<GapStatus, Meta> = {
  open: { label: '待处理', type: 'danger' },
  in_review: { label: '处理中', type: 'warning' },
  resolved: { label: '已解决', type: 'success' },
  rejected: { label: '已驳回', type: 'info' },
  duplicate: { label: '重复', type: 'info' },
}

export const KO_TYPE_LABEL: Record<KoType, string> = {
  faq: 'FAQ',
  qa: '问答',
  card: '知识卡片',
  policy_summary: '制度摘要',
}

export const KO_STATUS_META: Record<KoStatus, Meta> = {
  draft: { label: '草稿', type: 'info' },
  pending_review: { label: '待审核', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  deprecated: { label: '已下线', type: 'danger' },
}

export const KO_VERSION_STATUS_META: Record<KoVersionStatus, Meta> = {
  pending_review: { label: '待审核', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  rejected: { label: '已驳回', type: 'danger' },
  withdrawn: { label: '已撤回', type: 'info' },
  superseded: { label: '已被替代', type: 'info' },
  deprecated: { label: '已下线', type: 'danger' },
}

export const REVIEW_STATUS_META: Record<ReviewStatus, Meta> = {
  pending: { label: '待审核', type: 'warning' },
  approved: { label: '已通过', type: 'success' },
  rejected: { label: '已驳回', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

export const VERDICT_META: Record<ConflictVerdict, Meta> = {
  conflict: { label: '内容矛盾', type: 'danger' },
  duplicate: { label: '内容重复', type: 'warning' },
  consistent: { label: '一致', type: 'success' },
  unrelated: { label: '无关', type: 'info' },
  unknown: { label: '未能判断', type: 'info' },
}

export const ORIGIN_LABEL: Record<string, string> = {
  manual: '手工创建',
  gap: '来自缺口',
  document: '文档生成',
}

export function metaOf<K extends string>(map: Record<K, Meta>, key: string): Meta {
  return (map as Record<string, Meta>)[key] ?? { label: key, type: 'info' }
}

/** Conflicts worth a warning on the review page. */
export function isWarning(verdict: ConflictVerdict): boolean {
  return verdict === 'conflict' || verdict === 'duplicate'
}
