import type { RouteLocationNormalized, RouteLocationRaw, Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { menuRoutes, type MenuRoute } from './routes'

/** First route (depth-first) the user may open, used for `/` and section roots. */
export function firstAccessible(
  routes: MenuRoute[],
  can: (p: MenuRoute['meta']['permission']) => boolean,
): MenuRoute | undefined {
  for (const route of routes) {
    if (!can(route.meta.permission)) continue
    if (route.children?.length) {
      const child = firstAccessible(route.children, can)
      if (child) return child
      continue
    }
    return route
  }
  return undefined
}

export async function authGuard(to: RouteLocationNormalized): Promise<true | RouteLocationRaw> {
  const auth = useAuthStore()
  if (!auth.isAuthenticated) {
    await auth.loadProfile()
  }
  const can = (p: MenuRoute['meta']['permission']) => auth.can(p)

  const section = menuRoutes.find((r) => r.name === to.name && r.children?.length)
  if (to.name === 'home' || section) {
    const target = firstAccessible(section?.children ?? menuRoutes, can)
    return target ? { name: target.name } : { name: 'forbidden' }
  }
  const denied = to.matched.some((record) => !auth.can(record.meta.permission))
  return denied ? { name: 'forbidden' } : true
}

export function installGuards(router: Router): void {
  router.beforeEach(authGuard)
  router.afterEach((to) => {
    const appTitle = import.meta.env.VITE_APP_TITLE ?? '企业知识库'
    document.title = to.meta.title ? `${to.meta.title} - ${appTitle}` : appTitle
  })
}
