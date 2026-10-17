import type {
  ConflictVerdict,
  GapStatus,
  GapType,
  KoStatus,
  KoType,
  KoVersionStatus,
  ReviewStatus,
} from '@/api/types'
import { t } from '@/i18n'

export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

interface Meta {
  label: string
  type: TagType
}

/** Labels are getters so they are translated at read time and follow locale switches. */
function metaMap<K extends string>(group: string, types: Record<K, TagType>): Record<K, Meta> {
  const map = {} as Record<K, Meta>
  for (const key of Object.keys(types) as K[]) {
    map[key] = {
      type: types[key],
      get label() {
        return t(`curation.meta.${group}.${key}`)
      },
    }
  }
  return map
}

function labelMap<K extends string>(group: string, keys: readonly K[]): Record<K, string> {
  const map = {} as Record<K, string>
  for (const key of keys) {
    Object.defineProperty(map, key, {
      enumerable: true,
      get: () => t(`curation.meta.${group}.${key}`),
    })
  }
  return map
}

export const GAP_TYPE_META: Record<GapType, Meta> = metaMap('gapType', {
  no_evidence: 'danger',
  low_grounding: 'warning',
  negative_feedback: 'warning',
  user_request: 'primary',
})

export const GAP_STATUS_META: Record<GapStatus, Meta> = metaMap('gapStatus', {
  open: 'danger',
  in_review: 'warning',
  resolved: 'success',
  rejected: 'info',
  duplicate: 'info',
})

export const KO_TYPE_LABEL: Record<KoType, string> = labelMap<KoType>('koType', [
  'faq',
  'qa',
  'card',
  'policy_summary',
])

export const KO_STATUS_META: Record<KoStatus, Meta> = metaMap('koStatus', {
  draft: 'info',
  pending_review: 'warning',
  published: 'success',
  deprecated: 'danger',
})

export const KO_VERSION_STATUS_META: Record<KoVersionStatus, Meta> = metaMap('koVersionStatus', {
  pending_review: 'warning',
  published: 'success',
  rejected: 'danger',
  withdrawn: 'info',
  superseded: 'info',
  deprecated: 'danger',
})

export const REVIEW_STATUS_META: Record<ReviewStatus, Meta> = metaMap('reviewStatus', {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  cancelled: 'info',
})

export const VERDICT_META: Record<ConflictVerdict, Meta> = metaMap('verdict', {
  conflict: 'danger',
  duplicate: 'warning',
  consistent: 'success',
  unrelated: 'info',
  unknown: 'info',
})

export const ORIGIN_LABEL: Record<string, string> = labelMap('origin', [
  'manual',
  'gap',
  'document',
])

export function metaOf<K extends string>(map: Record<K, Meta>, key: string): Meta {
  return (map as Record<string, Meta>)[key] ?? { label: key, type: 'info' }
}

/** Conflicts worth a warning on the review page. */
export function isWarning(verdict: ConflictVerdict): boolean {
  return verdict === 'conflict' || verdict === 'duplicate'
}
