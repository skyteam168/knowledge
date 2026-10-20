import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import DocumentComments from '../DocumentComments.vue'
import type { DocComment } from '@/api/types'

const api = vi.hoisted(() => ({
  listComments: vi.fn(),
  createComment: vi.fn(),
  resolveComment: vi.fn(),
}))
vi.mock('@/api/collab', () => ({
  ...api,
  deleteComment: vi.fn(),
  updateComment: vi.fn(),
}))
vi.mock('@/api/knowledge', () => ({ searchPrincipals: vi.fn().mockResolvedValue([]) }))

function comment(id: string, extra: Partial<DocComment> = {}): DocComment {
  return {
    id,
    parent_id: null,
    author_id: 'u1',
    author_name: 'Carol',
    body: `body ${id}`,
    mentions: [],
    document_version: 2,
    created_at: '2026-10-20T00:00:00Z',
    edited: false,
    resolved_at: null,
    resolved_by_name: null,
    deleted: false,
    can_edit: true,
    can_delete: true,
    can_resolve: true,
    replies: [],
    ...extra,
  }
}

describe('DocumentComments', () => {
  beforeEach(() => {
    api.listComments.mockReset().mockResolvedValue([
      comment('c1', {
        mentions: [{ id: 'u2', name: 'Bob' }],
        replies: [comment('r1', { parent_id: 'c1', author_name: 'Bob', can_resolve: false })],
      }),
      comment('c2', { resolved_at: '2026-10-20T01:00:00Z', resolved_by_name: 'Bob' }),
    ])
    api.createComment.mockReset().mockResolvedValue(comment('c3'))
    api.resolveComment.mockReset().mockResolvedValue(comment('c1'))
  })

  it('shows open threads with replies and counts them', async () => {
    const wrapper = mount(DocumentComments, {
      props: { docId: 'd1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(wrapper.emitted('count')?.[0]).toEqual([1])
    const text = wrapper.get('[data-test="doc-comments"]').text()
    expect(text).toContain('@Bob')
    expect(text).toContain('body r1')
    expect(text).not.toContain('body c2')
    expect(wrapper.findAll('[data-test="comment-resolve"]')).toHaveLength(1)
  })

  it('posts a comment with mentions and reloads', async () => {
    const wrapper = mount(DocumentComments, {
      props: { docId: 'd1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    await wrapper.get('textarea[data-test="comment-body"]').setValue('参数已过时')
    await wrapper.get('[data-test="comment-submit"]').trigger('click')
    await flushPromises()
    expect(api.createComment).toHaveBeenCalledWith('d1', {
      body: '参数已过时',
      parent_id: null,
      mentions: [],
    })
    expect(api.listComments).toHaveBeenCalledTimes(2)
  })
})
