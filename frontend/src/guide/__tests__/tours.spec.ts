import { describe, expect, it } from 'vitest'
import { hasAnyPermission, type PermissionRequirement } from '@/utils/permission'
import { LAYOUT_TOUR, TOURS, findTour, resolveSteps, tourForRoute } from '../tours'

function canWith(perms: string[]) {
  return (required: PermissionRequirement | undefined) => hasAnyPermission(perms, required)
}

describe('tours', () => {
  it('has unique keys and maps page routes to their tour', () => {
    const keys = TOURS.map((t) => t.key)
    expect(new Set(keys).size).toBe(keys.length)
    expect(tourForRoute('assistant')?.key).toBe('assistant')
    expect(tourForRoute('knowledge-base')?.key).toBe('kb-detail')
    expect(tourForRoute('admin-users')).toBeUndefined()
    expect(tourForRoute(undefined)).toBeUndefined()
  })

  it('drops steps the user may not see and steps whose target is missing', () => {
    const layout = findTour(LAYOUT_TOUR)!
    const all = resolveSteps(layout, canWith(['*']), () => true)
    const basic = resolveSteps(layout, canWith(['chat:use']), () => true)
    expect(basic.length).toBeLessThan(all.length)
    expect(basic.some((s) => s.target === 'menu-assistant')).toBe(true)
    expect(basic.some((s) => s.target === 'menu-admin')).toBe(false)
    expect(basic.some((s) => s.target === 'menu-knowledge')).toBe(false)

    const noTargets = resolveSteps(layout, canWith(['*']), () => false)
    expect(noTargets.length).toBeGreaterThan(0)
    expect(noTargets.every((s) => !s.target)).toBe(true)
  })

  it('checks targets in the DOM by default', () => {
    document.body.innerHTML = '<div data-guide="kb-search"></div>'
    const steps = resolveSteps(findTour('knowledge')!, canWith(['*']))
    expect(steps.some((s) => s.target === 'kb-search')).toBe(true)
    expect(steps.some((s) => s.target === 'kb-table')).toBe(false)
    document.body.innerHTML = ''
  })
})
