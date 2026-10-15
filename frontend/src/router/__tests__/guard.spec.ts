import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { authGuard } from '../guard'
import { routes } from '../routes'
import { fetchMe } from '@/api/auth'
import { makeProfile } from '@/test/fixtures'

vi.mock('@/api/auth', () => ({ fetchMe: vi.fn() }))
vi.mock('@/auth/client', () => ({ logout: vi.fn() }))

function makeRouter(): Router {
  const router = createRouter({ history: createMemoryHistory(), routes })
  router.beforeEach(authGuard)
  return router
}

describe('authGuard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchMe).mockReset()
  })

  it('loads the profile once and allows permitted routes', async () => {
    vi.mocked(fetchMe).mockResolvedValue(makeProfile(['chat:use', 'kb:read']))
    const router = makeRouter()
    await router.push('/knowledge')
    await router.push('/assistant')
    expect(router.currentRoute.value.name).toBe('assistant')
    expect(fetchMe).toHaveBeenCalledOnce()
  })

  it('redirects to 403 without permission', async () => {
    vi.mocked(fetchMe).mockResolvedValue(makeProfile(['chat:use']))
    const router = makeRouter()
    await router.push('/admin/users')
    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('sends / to the first accessible menu', async () => {
    vi.mocked(fetchMe).mockResolvedValue(makeProfile(['search:use']))
    const router = makeRouter()
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('search')
  })

  it('sends /admin to the first accessible admin page', async () => {
    vi.mocked(fetchMe).mockResolvedValue(makeProfile(['admin:role', 'admin:audit']))
    const router = makeRouter()
    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('admin-roles')
  })

  it('sends / to 403 when nothing is accessible', async () => {
    vi.mocked(fetchMe).mockResolvedValue(makeProfile([]))
    const router = makeRouter()
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('forbidden')
  })
})
