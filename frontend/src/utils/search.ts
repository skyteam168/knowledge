import type { SearchHit } from '@/api/types'
import { t } from '@/i18n'

/** Format names are not translated; `text` / `other` go through i18n. */
const DOC_TYPE_LABELS: Record<string, string> = {
  pdf: 'PDF',
  word: 'Word',
  excel: 'Excel',
  csv: 'CSV',
  ppt: 'PPT',
  markdown: 'Markdown',
  html: 'HTML',
}
const TRANSLATED_DOC_TYPES = new Set(['text', 'other'])

export function docTypeLabel(type: string): string {
  if (TRANSLATED_DOC_TYPES.has(type)) return t(`search.docTypes.${type}`)
  return DOC_TYPE_LABELS[type] ?? type
}

/** "Page 3" / "Pages 3-5" / "Sheet Stock" / "Slide 2" (localized), joined with " · ". */
export function hitLocation(
  hit: Pick<SearchHit, 'page_start' | 'page_end' | 'sheet_name' | 'slide_number'>,
): string {
  const parts: string[] = []
  if (hit.page_start != null) {
    parts.push(
      hit.page_end != null && hit.page_end !== hit.page_start
        ? t('search.location.pages', { start: hit.page_start, end: hit.page_end })
        : t('search.location.page', { page: hit.page_start }),
    )
  }
  if (hit.sheet_name) parts.push(t('search.location.sheet', { name: hit.sheet_name }))
  if (hit.slide_number != null) parts.push(t('search.location.slide', { n: hit.slide_number }))
  return parts.join(' · ')
}

/**
 * Local calendar days [start, end] (YYYY-MM-DD) -> UTC instants [from, to) where `to` is the
 * midnight after `end`, matching the API's exclusive upper bound.
 */
export function dayRangeToParams(range: [string, string] | null | undefined): {
  date_from?: string
  date_to?: string
} {
  if (!range) return {}
  const [start, end] = range.map((d) => {
    const [y, m, day] = d.split('-').map(Number)
    return new Date(y, m - 1, day)
  })
  end.setDate(end.getDate() + 1)
  return { date_from: start.toISOString(), date_to: end.toISOString() }
}

export function formatScore(value: number | null | undefined, digits = 4): string {
  return value == null ? '-' : value.toFixed(digits)
}

export function formatRank(value: number | null | undefined): string {
  return value == null ? '-' : `#${value}`
}
