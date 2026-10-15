import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import AppLayout from '../AppLayout.vue'
import { routes } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'
import { vPermission } from '@/directives/permission'
import { makeProfile } from '@/test/fixtures'

vi.mock('@/api/system', () => ({
  fetchReadiness: vi.fn().mockResolvedValue({ status: 'ready', checks: {} }),
}))
vi.mock('@/api/admin', () => ({
  listAuditLogs: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, size: 20 }),
}))
vi.mock('@/api/search', () => ({
  getSearchOptions: vi.fn().mockResolvedValue({ doc_types: [], tags: [], can_debug: false }),
  listRetrievalProfiles: vi.fn().mockResolvedValue([]),
  search: vi.fn(),
}))
vi.mock('@/api/knowledge', () => ({
  listKnowledgeBases: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, size: 50 }),
}))
vi.mock('@/api/chat', () => ({
  listConversations: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, size: 50 }),
  getConversation: vi.fn(),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  updateConversation: vi.fn(),
  askQuestion: vi.fn(),
  requestKnowledge: vi.fn(),
  sendFeedback: vi.fn(),
  getCitationSource: vi.fn(),
}))
vi.mock('@/api/curation', () => ({
  getUnreadCount: vi.fn().mockResolvedValue({ unread: 3 }),
}))
vi.mock('@/api/guides', () => ({
  listGuideProgress: vi.fn().mockRejectedValue(new Error('offline')),
  saveGuideProgress: vi.fn(),
  resetGuideProgress: vi.fn(),
}))
vi.mock('@/auth/client', () => ({
  getValidToken: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}))

async function mountWith(permissions: string[], path: string, globalElementPlus = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setProfile(makeProfile(permissions))
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(AppLayout, {
    global: {
      plugins: globalElementPlus ? [pinia, router, ElementPlus] : [pinia, router],
      directives: { permission: vPermission },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('AppLayout', () => {
  it('shows every menu for a superuser and switches route', async () => {
    const { wrapper, router } = await mountWith(['*'], '/assistant')
    const text = wrapper.text()
    for (const title of ['AI 助手', '知识库', '搜索', '知识运营', '管理', '分析']) {
      expect(text).toContain(title)
    }
    expect(wrapper.get('[data-test="readiness-tag"]').text()).toBe('服务正常')
    expect(wrapper.find('.layout__bell').text()).toContain('3')
    expect(wrapper.get('[data-test="user-menu"]').text()).toContain('Alice')
    expect(wrapper.find('[data-test="help-menu"]').exists()).toBe(true)
    for (const target of ['menu-assistant', 'menu-admin', 'menu-curation', 'global-search']) {
      expect(wrapper.find(`[data-guide="${target}"]`).exists()).toBe(true)
    }

    await router.push('/search')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('search')
    expect(wrapper.text()).toContain('支持行内筛选')
  })

  it('resolves every Element Plus component without global registration', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const { wrapper, router } = await mountWith(['*'], '/assistant', false)
      await router.push('/search')
      await flushPromises()
      const unresolved = warn.mock.calls
        .map((args) => String(args[0]))
        .filter((msg) => msg.includes('Failed to resolve'))
      expect(unresolved).toEqual([])
      expect(wrapper.find('.el-menu').exists()).toBe(true)
    } finally {
      warn.mockRestore()
    }
  })

  it('hides menus the user lacks permission for', async () => {
    const { wrapper } = await mountWith(['kb:read', 'chat:use', 'search:use'], '/assistant')
    const menu = wrapper.get('[data-test="side-menu"]').text()
    expect(menu).toContain('AI 助手')
    expect(menu).toContain('知识库')
    expect(menu).toContain('搜索')
    expect(menu).not.toContain('管理')
    expect(menu).not.toContain('分析')
    expect(menu).not.toContain('知识运营')
  })

  it('shows the knowledge-loop pages an editor may use', async () => {
    const { wrapper } = await mountWith(['gap:review', 'ko:edit'], '/assistant')
    const menu = wrapper.get('[data-test="side-menu"]').html()
    expect(menu).toContain('知识运营')
    expect(menu).toContain('知识缺口')
    expect(menu).toContain('知识条目')
    expect(menu).not.toContain('发布审核')
  })

  it('shows only the admin sub-pages that are granted', async () => {
    const { wrapper } = await mountWith(['admin:audit'], '/admin/audit-logs')
    const menu = wrapper.get('[data-test="side-menu"]').html()
    expect(menu).toContain('管理')
    expect(menu).toContain('审计日志')
    expect(menu).not.toContain('用户管理')
    expect(menu).not.toContain('角色权限')
  })
})
