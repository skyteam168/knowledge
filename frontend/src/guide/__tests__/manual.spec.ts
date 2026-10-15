import { describe, expect, it } from 'vitest'
import { hasAnyPermission, type PermissionRequirement } from '@/utils/permission'
import { visibleManual } from '../manual'

function canWith(perms: string[]) {
  return (required: PermissionRequirement | undefined) => hasAnyPermission(perms, required)
}

describe('visibleManual', () => {
  it('shows everything to a superuser', () => {
    const { sections, faq } = visibleManual(canWith(['*']))
    expect(sections.map((s) => s.id)).toEqual([
      'start',
      'assistant',
      'knowledge',
      'search',
      'curation',
      'admin',
      'analytics',
    ])
    expect(faq.length).toBeGreaterThan(0)
  })

  it('hides sections, topics and steps the user lacks permission for', () => {
    const { sections, faq } = visibleManual(canWith(['chat:use', 'kb:read', 'search:use']))
    const ids = sections.map((s) => s.id)
    expect(ids).toEqual(['start', 'assistant', 'knowledge', 'search'])

    const knowledge = sections.find((s) => s.id === 'knowledge')!
    expect(knowledge.topics.map((t) => t.title)).toEqual(['浏览文档'])
    expect(faq.some((f) => f.permission === 'doc:upload')).toBe(false)
  })

  it('keeps only granted steps inside a mixed topic and drops empty topics', () => {
    const { sections } = visibleManual(canWith(['admin:audit']))
    const admin = sections.find((s) => s.id === 'admin')!
    expect(admin.topics.map((t) => t.title)).toEqual(['审计与开放平台'])
    expect(admin.topics[0]!.steps.map((s) => s.title)).toEqual(['审计日志'])

    const start = sections.find((s) => s.id === 'start')!
    expect(start.topics[0]!.steps.some((s) => s.permission === 'chat:use')).toBe(false)
  })
})
