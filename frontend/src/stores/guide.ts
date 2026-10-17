import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { listGuideProgress, resetGuideProgress, saveGuideProgress } from '@/api/guides'
import type { GuideProgress, GuideStatus } from '@/api/types'
import {
  findTour,
  resolveStepIndexes,
  stepsAt,
  type ResolvedStep,
  type TourDef,
} from '@/guide/tours'
import { useAuthStore } from './auth'

export const useGuideStore = defineStore('guide', () => {
  const progress = ref<Record<string, GuideProgress>>({})
  // Tours only auto-play once progress is known, so a failed load never nags the user.
  const loaded = ref(false)
  // Key + step indexes rather than resolved text, so a running tour follows locale switches.
  const activeKey = ref<string | null>(null)
  const stepIndexes = ref<number[]>([])
  const active = computed<TourDef | null>(() =>
    activeKey.value ? (findTour(activeKey.value) ?? null) : null,
  )
  const steps = computed<ResolvedStep[]>(() =>
    active.value ? stepsAt(active.value, stepIndexes.value) : [],
  )
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
    const indexes = resolveStepIndexes(tour, auth.can)
    if (!indexes.length) return false
    stepIndexes.value = indexes
    activeKey.value = tour.key
    return true
  }

  async function end(status: GuideStatus): Promise<void> {
    const tour = active.value
    activeKey.value = null
    stepIndexes.value = []
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
