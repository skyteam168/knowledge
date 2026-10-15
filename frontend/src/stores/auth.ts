import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchMe } from '@/api/auth'
import type { MeResponse } from '@/api/types'
import { logout as authLogout } from '@/auth/client'
import { hasAnyPermission, type PermissionRequirement } from '@/utils/permission'

export const useAuthStore = defineStore('auth', () => {
  const profile = ref<MeResponse | null>(null)

  const isAuthenticated = computed(() => profile.value !== null)
  const permissions = computed<string[]>(() => profile.value?.permissions ?? [])
  const displayName = computed(() => profile.value?.display_name || profile.value?.username || '')

  async function loadProfile(): Promise<MeResponse> {
    profile.value = await fetchMe()
    return profile.value
  }

  function setProfile(value: MeResponse | null): void {
    profile.value = value
  }

  function can(required: PermissionRequirement | undefined): boolean {
    return hasAnyPermission(permissions.value, required)
  }

  async function logout(): Promise<void> {
    profile.value = null
    await authLogout()
  }

  return {
    profile,
    isAuthenticated,
    permissions,
    displayName,
    loadProfile,
    setProfile,
    can,
    logout,
  }
})
