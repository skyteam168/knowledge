import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

export interface TagView {
  /** Route path without query; one tab (and one cached page instance) per path. */
  key: string
  fullPath: string
  name: string
  title: string
  affix?: boolean
}

const STORAGE_KEY = 'ekb.tags'
const MAX_TAGS = 20
const UNTRACKED = new Set(['forbidden', 'not-found', 'home'])

function restore(): TagView[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as TagView[]) : []
    return Array.isArray(parsed) ? parsed.filter((t) => t && t.key && t.fullPath) : []
  } catch {
    return []
  }
}

export const useTagsStore = defineStore('tags', () => {
  const tags = ref<TagView[]>(restore())
  /** Bumped per key to force a cached page to remount ("刷新"). */
  const refreshSeq = ref<Record<string, number>>({})

  const cachedKeys = computed(() => tags.value.map((t) => t.key))

  watch(
    tags,
    (value) => {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
      } catch {
        /* storage unavailable: tabs simply don't survive reloads */
      }
    },
    { deep: true },
  )

  function track(route: RouteLocationNormalizedLoaded): void {
    const name = typeof route.name === 'string' ? route.name : ''
    if (!name || UNTRACKED.has(name) || !route.meta.title) return
    const existing = tags.value.find((t) => t.key === route.path)
    if (existing) {
      existing.fullPath = route.fullPath
      existing.title = route.meta.title
      return
    }
    tags.value.push({ key: route.path, fullPath: route.fullPath, name, title: route.meta.title })
    const closable = tags.value.filter((t) => !t.affix)
    if (closable.length > MAX_TAGS) remove([closable[0].key])
  }

  function remove(keys: string[]): void {
    const drop = new Set(keys)
    tags.value = tags.value.filter((t) => t.affix || !drop.has(t.key))
  }

  /** Returns the tag to navigate to when `key` was the active one, if any remain. */
  function close(key: string): TagView | undefined {
    const index = tags.value.findIndex((t) => t.key === key)
    remove([key])
    return tags.value[Math.min(index, tags.value.length - 1)]
  }

  function closeOthers(key: string): void {
    remove(tags.value.filter((t) => t.key !== key).map((t) => t.key))
  }

  function closeRight(key: string): void {
    const index = tags.value.findIndex((t) => t.key === key)
    remove(tags.value.slice(index + 1).map((t) => t.key))
  }

  function closeLeft(key: string): void {
    const index = tags.value.findIndex((t) => t.key === key)
    remove(tags.value.slice(0, Math.max(index, 0)).map((t) => t.key))
  }

  function closeAll(): void {
    remove(tags.value.map((t) => t.key))
  }

  function refresh(key: string): void {
    refreshSeq.value = { ...refreshSeq.value, [key]: (refreshSeq.value[key] ?? 0) + 1 }
  }

  function move(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return
    const next = [...tags.value]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    tags.value = next
  }

  function reset(): void {
    tags.value = []
    refreshSeq.value = {}
  }

  return {
    tags,
    cachedKeys,
    refreshSeq,
    track,
    close,
    closeOthers,
    closeRight,
    closeLeft,
    closeAll,
    refresh,
    move,
    reset,
  }
})
