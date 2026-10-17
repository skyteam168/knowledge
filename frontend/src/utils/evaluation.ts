import type { EvalMetrics, EvalRunStatus } from '@/api/types'
import { t } from '@/i18n'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

export const RUN_STATUS_META: Record<EvalRunStatus, { type: TagType }> = {
  pending: { type: 'info' },
  running: { type: 'primary' },
  done: { type: 'success' },
  failed: { type: 'danger' },
}

export function runStatusLabel(status: EvalRunStatus): string {
  return t(`evaluation.runStatus.${status}`)
}

/** Labels that read the same in every locale (metric names). */
export const METRIC_LABELS: Record<string, string> = {
  'recall@5': 'Recall@5',
  'recall@10': 'Recall@10',
  mrr: 'MRR',
  'ndcg@10': 'nDCG@10',
  'chunk_recall@5': 'Chunk Recall@5',
  'chunk_recall@10': 'Chunk Recall@10',
  chunk_mrr: 'Chunk MRR',
  'chunk_ndcg@10': 'Chunk nDCG@10',
}

/** Metrics whose label lives in `evaluation.metrics.<key>`. */
const TRANSLATED_METRICS = new Set([
  'faithfulness',
  'answer_relevance',
  'citation_accuracy',
  'citation_precision',
  'answered',
  'grounded',
  'degraded',
  'retrieved',
  'latency_ms_avg',
  'cases',
  'errors',
])

/** Metrics shown first, in this order; the rest follow alphabetically. */
export const PRIMARY_METRICS = [
  'recall@5',
  'recall@10',
  'mrr',
  'ndcg@10',
  'faithfulness',
  'answer_relevance',
  'citation_accuracy',
  'citation_precision',
]

/** Metrics that are scores in [0, 1] (shown as percentages / bar charts). */
const NON_SCORE_METRICS = new Set(['retrieved', 'latency_ms_avg', 'cases', 'errors'])

export function isScoreMetric(key: string): boolean {
  return !NON_SCORE_METRICS.has(key)
}

export function metricLabel(key: string): string {
  if (TRANSLATED_METRICS.has(key)) return t(`evaluation.metrics.${key}`)
  return METRIC_LABELS[key] ?? key
}

export function sortMetricKeys(keys: Iterable<string>): string[] {
  const all = new Set(keys)
  const primary = PRIMARY_METRICS.filter((k) => all.has(k))
  const rest = [...all].filter((k) => !PRIMARY_METRICS.includes(k)).sort()
  return [...primary, ...rest]
}

export function formatMetric(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (!isScoreMetric(key)) return Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${(value * 100).toFixed(1)}%`
}

/** Best value per metric across runs (higher is better, except latency / errors / degraded). */
export function bestRunPerMetric(
  keys: string[],
  runs: { id: string; metrics: EvalMetrics }[],
): Record<string, string | null> {
  const lowerIsBetter = new Set(['latency_ms_avg', 'errors', 'degraded'])
  const best: Record<string, string | null> = {}
  for (const key of keys) {
    let winner: string | null = null
    let winnerValue: number | null = null
    let tie = false
    for (const run of runs) {
      const value = run.metrics[key]
      if (value === null || value === undefined) continue
      if (winnerValue === null) {
        winner = run.id
        winnerValue = value
        continue
      }
      const better = lowerIsBetter.has(key) ? value < winnerValue : value > winnerValue
      if (better) {
        winner = run.id
        winnerValue = value
        tie = false
      } else if (value === winnerValue) {
        tie = true
      }
    }
    best[key] = tie ? null : winner
  }
  return best
}

export function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
