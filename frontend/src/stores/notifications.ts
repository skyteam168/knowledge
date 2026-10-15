import { ref } from 'vue'
import { defineStore } from 'pinia'
import { getUnreadCount } from '@/api/curation'

const POLL_MS = 60_000

export const useNotificationStore = defineStore('notifications', () => {
  const unread = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh(): Promise<void> {
    try {
      unread.value = (await getUnreadCount()).unread
    } catch {
      // Polling is best effort; the next tick retries.
    }
  }

  function startPolling(): void {
    if (timer) return
    void refresh()
    timer = setInterval(() => void refresh(), POLL_MS)
  }

  function stopPolling(): void {
    if (timer) clearInterval(timer)
    timer = null
  }

  return { unread, refresh, startPolling, stopPolling }
})
