import { createRouter, createWebHistory } from 'vue-router'
import { installGuards } from './guard'
import { routes } from './routes'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

installGuards(router)

/** After a frontend rebuild, in-memory lazy imports still point at old hashed chunks → 404. */
function isChunkLoadError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error ?? '')
  return (
    /Failed to fetch dynamically imported module/i.test(msg) ||
    /error loading dynamically imported module/i.test(msg) ||
    /Importing a module script failed/i.test(msg) ||
    /Loading chunk [\w-]+ failed/i.test(msg)
  )
}

const CHUNK_RELOAD_KEY = 'ekb:chunk-reload'
router.onError((error, to) => {
  if (!isChunkLoadError(error)) return
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || 0)
  if (Date.now() - last < 10_000) return
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  window.location.assign(to.fullPath)
})

export default router
