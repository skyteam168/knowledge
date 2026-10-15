import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import GuideTour from '../GuideTour.vue'
import { listGuideProgress, saveGuideProgress } from '@/api/guides'
import type { GuideProgress } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useGuideStore } from '@/stores/guide'
import { LAYOUT_TOUR, findTour } from '@/guide/tours'
import { makeProfile } from '@/test/fixtures'

vi.mock('@/api/guides', () => ({
  listGuideProgress: vi.fn(),
  saveGuideProgress: vi.fn(),
  resetGuideProgress: vi.fn(),
}))

const Page = defineComponent({
  render: () => h('div', [h('div', { 'data-guide': 'search-input' })]),
})

function row(key: string, status: GuideProgress['status']): GuideProgress {
  return { guide_key: key, version: findTour(key)!.version, status, updated_at: '' }
}

async function mountTour(progress: GuideProgress[], path = '/search') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setProfile(makeProfile(['*']))
  vi.mocked(listGuideProgress).mockResolvedValue(progress)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/search', name: 'search', component: Page },
      { path: '/other', name: 'other', component: Page },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(() => h('div', [h(Page), h(GuideTour, { settleMs: 0 })]), {
    global: { plugins: [pinia, router, ElementPlus] },
    attachTo: document.body,
  })
  await flushPromises()
  await new Promise((r) => setTimeout(r, 10))
  await flushPromises()
  return { wrapper, guide: useGuideStore(), router }
}

describe('GuideTour', () => {
  beforeEach(() => {
    vi.mocked(saveGuideProgress).mockReset()
    vi.mocked(saveGuideProgress).mockImplementation(async (key, version, status) => ({
      guide_key: key,
      version,
      status: status ?? 'completed',
      updated_at: '',
    }))
  })

  it('plays the welcome tour first for a new user', async () => {
    const { wrapper, guide } = await mountTour([])
    expect(guide.active?.key).toBe(LAYOUT_TOUR)
    wrapper.unmount()
  })

  it('plays the page tour once the welcome tour is done', async () => {
    const { wrapper, guide } = await mountTour([row(LAYOUT_TOUR, 'completed')])
    expect(guide.active?.key).toBe('search')
    expect(guide.steps.map((s) => s.target)).toEqual(['search-input'])
    wrapper.unmount()
  })

  it('stays quiet after the user skipped the welcome tour', async () => {
    const { wrapper, guide } = await mountTour([row(LAYOUT_TOUR, 'skipped')])
    expect(guide.running).toBe(false)
    wrapper.unmount()
  })

  it('does nothing on pages without a tour or already seen', async () => {
    const a = await mountTour([row(LAYOUT_TOUR, 'completed')], '/other')
    expect(a.guide.running).toBe(false)
    a.wrapper.unmount()

    const b = await mountTour([row(LAYOUT_TOUR, 'completed'), row('search', 'completed')])
    expect(b.guide.running).toBe(false)
    b.wrapper.unmount()
  })

  it('records a skip when the user closes the tour', async () => {
    const { wrapper, guide } = await mountTour([row(LAYOUT_TOUR, 'completed')])
    expect(guide.running).toBe(true)
    expect(document.querySelector('[data-test="guide-step"]')?.textContent).toContain('1 / 1')
    const close = document.querySelector<HTMLElement>('.el-tour__closebtn')
    expect(close).not.toBeNull()
    close!.click()
    await flushPromises()
    expect(saveGuideProgress).toHaveBeenCalledWith('search', findTour('search')!.version, 'skipped')
    expect(guide.running).toBe(false)
    wrapper.unmount()
  })
})
