import type { Directive } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { PermissionRequirement } from '@/utils/permission'

/**
 * Removes the element when the current user lacks every listed permission.
 * Usage: v-permission="'admin:user'" or v-permission="['admin:user', 'admin:role']"
 */
export const vPermission: Directive<HTMLElement, PermissionRequirement> = {
  mounted(el, binding) {
    if (!useAuthStore().can(binding.value)) {
      el.parentNode?.removeChild(el)
    }
  },
}
