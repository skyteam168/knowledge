import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import GuideView from '../GuideView.vue'
import { useAuthStore } from '@/stores/auth'
import { useGuideStore } from '@/stores/guide'
import { LAYOUT_TOUR } from '@/guide/tours'
import { makeProfile } from '@/test/fixtures'

vi.mock('@/api/guides', () => ({
  listGuideProgress: vi.fn().mockResolvedValue([]),
  saveGuideProgress: vi.fn(),
  resetGuideProgress: vi.fn(),
}))

const Blank = defineComponent({ render: () => h('div') })

async function mountView(perms: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setProfile(makeProfile(perms))
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/guide', name: 'guide', component: Blank },
      { path: '/assistant', name: 'assistant', component: Blank },
      { path: '/search', name: 'search', component: Blank },
    ],
  })
  await router.push('/guide')
  await router.isReady()
  const wrapper = mount(GuideView, { global: { plugins: [pinia, router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router, guide: useGuideStore() }
}

describe('GuideView', () => {
  it('lists only the sections the user may use', async () => {
    const { wrapper } = await mountView(['chat:use', 'search:use'])
    expect(wrapper.find('[data-test="guide-section-start"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guide-section-assistant"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guide-section-search"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="guide-section-knowledge"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="guide-section-admin"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="guide-faq"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('去试试')
  })

  it('"去试试" opens the page', async () => {
    const { wrapper, router } = await mountView(['chat:use'])
    const section = wrapper.get('[data-test="guide-section-assistant"]')
    const tryBtn = section.findAll('button').find((b) => b.text() === '去试试')!
    await tryBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('assistant')
  })

  it('plays the welcome tour from the quick-start section', async () => {
    const { wrapper, guide } = await mountView(['chat:use'])
    await wrapper.get('[data-test="guide-play-start"]').trigger('click')
    await flushPromises()
    expect(guide.active?.key).toBe(LAYOUT_TOUR)
  })
})
