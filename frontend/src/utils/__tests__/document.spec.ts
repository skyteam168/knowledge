import { describe, expect, it } from 'vitest'
import {
  atLeast,
  documentStatus,
  isMarkdownFile,
  reviewIntervalLabel,
  reviewStatus,
} from '@/utils/document'
import { formatBytes, isAcceptedFile } from '@/utils/file'

describe('documentStatus', () => {
  it('treats parsed without chunks as still chunking', () => {
    expect(documentStatus({ status: 'parsed', chunk_count: null })).toMatchObject({
      label: '切分中',
      active: true,
    })
    expect(documentStatus({ status: 'parsed', chunk_count: 12 })).toMatchObject({
      label: '已切分',
      active: false,
      progress: 100,
    })
  })

  it('marks failures as settled', () => {
    expect(documentStatus({ status: 'failed', chunk_count: null })).toMatchObject({
      type: 'danger',
      active: false,
    })
    expect(documentStatus({ status: 'uploaded', chunk_count: null }).active).toBe(true)
  })
})

describe('review helpers', () => {
  it('labels states and intervals', () => {
    expect(reviewStatus('overdue')).toEqual({ label: '复核已逾期', type: 'danger' })
    expect(reviewStatus('due_soon').type).toBe('warning')
    expect(reviewIntervalLabel(90)).toBe('每 90 天')
    expect(reviewIntervalLabel(null)).toBe('不定期复核')
    expect(reviewIntervalLabel(0)).toBe('不定期复核')
  })
})

describe('isMarkdownFile', () => {
  it('recognizes markdown extensions', () => {
    expect(isMarkdownFile('说明.md')).toBe(true)
    expect(isMarkdownFile('README.markdown')).toBe(true)
    expect(isMarkdownFile('notes.txt')).toBe(false)
    expect(isMarkdownFile('a.pdf')).toBe(false)
  })
})

describe('atLeast', () => {
  it('compares ACL levels', () => {
    expect(atLeast('manage', 'edit')).toBe(true)
    expect(atLeast('read', 'edit')).toBe(false)
    expect(atLeast(null, 'read')).toBe(false)
  })
})

describe('file helpers', () => {
  it('formats sizes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(null)).toBe('-')
  })

  it('accepts supported extensions only', () => {
    expect(isAcceptedFile('手册.DOCX')).toBe(true)
    expect(isAcceptedFile('report.pdf')).toBe(true)
    expect(isAcceptedFile('旧版制度.doc')).toBe(true)
    expect(isAcceptedFile('setup.exe')).toBe(false)
    expect(isAcceptedFile('README')).toBe(false)
  })
})
