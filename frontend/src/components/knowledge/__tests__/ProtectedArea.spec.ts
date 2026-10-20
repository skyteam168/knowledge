import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import ProtectedArea from '../ProtectedArea.vue'
import { useAuthStore } from '@/stores/auth'
import type { MeResponse } from '@/api/types'

function mountArea(props: { watermark?: boolean; copyProtect?: boolean }) {
  return mount(ProtectedArea, {
    props,
    slots: { default: '<p class="content">工艺参数</p>' },
    global: { plugins: [ElementPlus] },
  })
}

describe('ProtectedArea', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useAuthStore().setProfile({
      id: 'u1',
      username: 'hien',
      display_name: 'Hien',
      employee_no: '26003932',
      permissions: [],
    } as unknown as MeResponse)
  })

  it('overlays a watermark with the viewer name, account and employee no.', () => {
    const layer = mountArea({ watermark: true }).get('[data-test="watermark-layer"]')
    const text = layer.attributes('data-watermark')
    expect(text).toContain('Hien')
    expect(text).toContain('hien · 26003932')
  })

  it('blocks copy and the context menu only when copy protection is on', () => {
    const open = mountArea({})
    const copy = new Event('copy', { cancelable: true })
    open.get('[data-test="protected-area"]').element.dispatchEvent(copy)
    expect(copy.defaultPrevented).toBe(false)
    expect(open.find('[data-test="watermark-layer"]').exists()).toBe(false)

    const locked = mountArea({ copyProtect: true })
    const area = locked.get('[data-test="protected-area"]')
    expect(area.classes()).toContain('protected--nocopy')
    const blocked = new Event('copy', { cancelable: true })
    area.element.dispatchEvent(blocked)
    expect(blocked.defaultPrevented).toBe(true)
    const menu = new Event('contextmenu', { cancelable: true })
    area.element.dispatchEvent(menu)
    expect(menu.defaultPrevented).toBe(true)
  })
})
