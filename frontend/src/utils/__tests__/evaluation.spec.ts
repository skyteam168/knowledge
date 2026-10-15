import { describe, expect, it } from 'vitest'
import { bestRunPerMetric, formatMetric, sortMetricKeys } from '../evaluation'

describe('evaluation utils', () => {
  it('orders primary metrics first, then the rest alphabetically', () => {
    expect(sortMetricKeys(['latency_ms_avg', 'mrr', 'answered', 'recall@5'])).toEqual([
      'recall@5',
      'mrr',
      'answered',
      'latency_ms_avg',
    ])
  })

  it('formats scores as percentages and counts as numbers', () => {
    expect(formatMetric('recall@5', 0.8333)).toBe('83.3%')
    expect(formatMetric('latency_ms_avg', 812.456)).toBe('812.5')
    expect(formatMetric('cases', 12)).toBe('12')
    expect(formatMetric('mrr', null)).toBe('—')
  })

  it('picks the best run per metric, lower is better for latency, null on ties', () => {
    const runs = [
      { id: 'a', metrics: { 'recall@5': 0.6, latency_ms_avg: 900, mrr: 0.5 } },
      { id: 'b', metrics: { 'recall@5': 0.8, latency_ms_avg: 1200, mrr: 0.5 } },
    ]
    expect(bestRunPerMetric(['recall@5', 'latency_ms_avg', 'mrr'], runs)).toEqual({
      'recall@5': 'b',
      latency_ms_avg: 'a',
      mrr: null,
    })
  })
})
