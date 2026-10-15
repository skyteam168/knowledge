import { describe, expect, it } from 'vitest'
import { dayRangeToParams, docTypeLabel, formatRank, formatScore, hitLocation } from '../search'

const empty = { page_start: null, page_end: null, sheet_name: null, slide_number: null }

describe('hitLocation', () => {
  it('formats pages, sheets and slides', () => {
    expect(hitLocation(empty)).toBe('')
    expect(hitLocation({ ...empty, page_start: 3, page_end: 3 })).toBe('第 3 页')
    expect(hitLocation({ ...empty, page_start: 3, page_end: 5 })).toBe('第 3-5 页')
    expect(hitLocation({ ...empty, sheet_name: '库存' })).toBe('工作表 库存')
    expect(hitLocation({ ...empty, page_start: 1, slide_number: 2 })).toBe(
      '第 1 页 · 第 2 张幻灯片',
    )
  })
})

describe('dayRangeToParams', () => {
  it('returns nothing without a range', () => {
    expect(dayRangeToParams(null)).toEqual({})
  })

  it('makes the end day inclusive via an exclusive next-midnight bound', () => {
    const { date_from, date_to } = dayRangeToParams(['2026-03-01', '2026-03-31'])
    expect(new Date(date_from!).getTime()).toBe(new Date(2026, 2, 1).getTime())
    expect(new Date(date_to!).getTime()).toBe(new Date(2026, 3, 1).getTime())
  })

  it('rolls over year ends', () => {
    const { date_to } = dayRangeToParams(['2026-12-31', '2026-12-31'])
    expect(new Date(date_to!).getTime()).toBe(new Date(2027, 0, 1).getTime())
  })
})

describe('formatting', () => {
  it('formats scores, ranks and doc types', () => {
    expect(formatScore(0.123456)).toBe('0.1235')
    expect(formatScore(null)).toBe('-')
    expect(formatRank(3)).toBe('#3')
    expect(formatRank(undefined)).toBe('-')
    expect(docTypeLabel('word')).toBe('Word')
    expect(docTypeLabel('weird')).toBe('weird')
  })
})
