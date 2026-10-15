import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { listGuideProgress, resetGuideProgress, saveGuideProgress } from '@/api/guides'
import type { GuideProgress, GuideStatus } from '@/api/types'
import { findTour, resolveSteps, type ResolvedStep, type TourDef } from '@/guide/tours'
import { useAuthStore } from './auth'

export const useGuideStore = defineStore('guide', () => {
  const progress = ref<Record<string, GuideProgress>>({})
  // Tours only auto-play once progress is known, so a failed load never nags the user.
  const loaded = ref(false)
  const active = ref<TourDef | null>(null)
  const steps = ref<ResolvedStep[]>([])
  const running = computed(() => active.value !== null)

  async function load(): Promise<void> {
    try {
      const rows = await listGuideProgress()
      progress.value = Object.fromEntries(rows.map((r) => [r.guide_key, r]))
      loaded.value = true
    } catch {
      loaded.value = false
    }
  }

  function seen(key: string): boolean {
    const tour = findTour(key)
    const row = progress.value[key]
    return !tour || (row !== undefined && row.version >= tour.version)
  }

  function needs(key: string): boolean {
    return loaded.value && !seen(key)
  }

  /** Opens a tour; returns false when nothing of it applies to this user or page. */
  function start(key: string): boolean {
    const tour = findTour(key)
    const auth = useAuthStore()
    if (!tour || running.value || !auth.can(tour.permission)) return false
    const resolved = resolveSteps(tour, auth.can)
    if (!resolved.length) return false
    steps.value = resolved
    active.value = tour
    return true
  }

  async function end(status: GuideStatus): Promise<void> {
    const tour = active.value
    active.value = null
    steps.value = []
    if (!tour) return
    const local: GuideProgress = {
      guide_key: tour.key,
      version: tour.version,
      status,
      updated_at: new Date().toISOString(),
    }
    progress.value = { ...progress.value, [tour.key]: local }
    try {
      progress.value = {
        ...progress.value,
        [tour.key]: await saveGuideProgress(tour.key, tour.version, status),
      }
    } catch {
      // Kept locally for this session; the tour may show again next time.
    }
  }

  async function reset(): Promise<void> {
    await resetGuideProgress()
    progress.value = {}
    loaded.value = true
  }

  return { progress, loaded, active, steps, running, load, seen, needs, start, end, reset }
})
