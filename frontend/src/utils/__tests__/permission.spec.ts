import { describe, expect, it } from 'vitest'
import { hasAnyPermission, hasPermission } from '../permission'

describe('permission', () => {
  it('matches exact codes', () => {
    expect(hasPermission(['kb:read'], 'kb:read')).toBe(true)
    expect(hasPermission(['kb:read'], 'kb:create')).toBe(false)
  })

  it('treats * as superuser', () => {
    expect(hasPermission(['*'], 'admin:role')).toBe(true)
  })

  it('expands prefix wildcards', () => {
    expect(hasPermission(['admin:*'], 'admin:user')).toBe(true)
    expect(hasPermission(['admin:*'], 'kb:read')).toBe(false)
  })

  it('accepts any-of requirements', () => {
    expect(hasAnyPermission(['admin:audit'], ['admin:user', 'admin:audit'])).toBe(true)
    expect(hasAnyPermission(['kb:read'], ['admin:user', 'admin:audit'])).toBe(false)
  })

  it('passes empty or missing requirements', () => {
    expect(hasAnyPermission([], undefined)).toBe(true)
    expect(hasAnyPermission([], [])).toBe(true)
  })
})
