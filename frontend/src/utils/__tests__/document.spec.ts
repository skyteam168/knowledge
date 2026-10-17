import { describe, expect, it } from 'vitest'
import { atLeast, documentStatus } from '@/utils/document'
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
