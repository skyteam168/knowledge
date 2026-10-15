import { describe, expect, it } from 'vitest'
import { diffLines, hasChanges } from '../diff'

describe('diffLines', () => {
  it('marks unchanged texts as equal', () => {
    const lines = diffLines('a\nb', 'a\nb')
    expect(lines).toEqual([
      { op: 'equal', text: 'a' },
      { op: 'equal', text: 'b' },
    ])
    expect(hasChanges(lines)).toBe(false)
  })

  it('finds inserted, removed and replaced lines', () => {
    expect(diffLines('a\nb\nc', 'a\nx\nc\nd')).toEqual([
      { op: 'equal', text: 'a' },
      { op: 'remove', text: 'b' },
      { op: 'add', text: 'x' },
      { op: 'equal', text: 'c' },
      { op: 'add', text: 'd' },
    ])
  })

  it('handles empty sides', () => {
    expect(diffLines('', 'a')).toEqual([{ op: 'add', text: 'a' }])
    expect(diffLines('a', '')).toEqual([{ op: 'remove', text: 'a' }])
    expect(diffLines('', '')).toEqual([])
  })
})
