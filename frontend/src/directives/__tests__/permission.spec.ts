import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, withDirectives } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { vPermission } from '../permission'
import { useAuthStore } from '@/stores/auth'
import { makeProfile } from '@/test/fixtures'

vi.mock('@/auth/client', () => ({ logout: vi.fn() }))

const Host = defineComponent({
  render: () =>
    h('div', [
      withDirectives(h('button', { 'data-test': 'create' }, '新建'), [[vPermission, 'kb:create']]),
      withDirectives(h('button', { 'data-test': 'admin' }, '管理'), [
        [vPermission, ['admin:user', 'admin:role']],
      ]),
    ]),
})

function mountAs(permissions: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setProfile(makeProfile(permissions))
  return mount(Host, { global: { plugins: [pinia] } })
}

describe('v-permission', () => {
  it('keeps elements the user is allowed to see', () => {
    const wrapper = mountAs(['kb:create', 'admin:role'])
    expect(wrapper.find('[data-test="create"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="admin"]').exists()).toBe(true)
  })

  it('removes elements without permission', () => {
    const wrapper = mountAs(['kb:read'])
    expect(wrapper.find('[data-test="create"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="admin"]').exists()).toBe(false)
  })
})
