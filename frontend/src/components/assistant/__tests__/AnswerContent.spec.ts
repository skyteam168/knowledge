import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AnswerContent from '../AnswerContent.vue'
import type { Citation } from '@/api/types'

const citation: Citation = {
  n: 1,
  document_id: 'doc-1',
  chunk_id: 'chunk-1',
  chunk_ids: ['chunk-1'],
  hit_chunk_ids: ['chunk-1'],
  title: '申洲邮箱网盘诊断地址',
  filename: 'diag.xlsx',
  kb_id: 'kb-1',
  kb_name: 'IT',
  doc_version: 1,
  heading_path: ['Sheet1'],
  page_start: null,
  page_end: null,
  sheet_name: 'Sheet1',
  slide_number: null,
  quote: '地址一：122.227.160.113',
  score: 0.9,
}

function mountAnswer() {
  return mount(AnswerContent, {
    props: { content: '地址一：122.227.160.113 [1]', citations: [citation] },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

function preview(): HTMLElement | null {
  return document.body.querySelector<HTMLElement>('[data-test="cite-preview"]')
}

describe('AnswerContent citation popover', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('stays open while the pointer moves from the marker into the popover', async () => {
    const wrapper = mountAnswer()
    const marker = wrapper.find('sup.cite')
    expect(marker.exists()).toBe(true)

    await marker.trigger('mouseover')
    await flushPromises()
    expect(preview()).not.toBeNull()

    await marker.trigger('mouseout', { relatedTarget: document.body })
    preview()!.dispatchEvent(new MouseEvent('mouseenter'))
    vi.advanceTimersByTime(500)
    await flushPromises()
    expect(preview()).not.toBeNull()

    preview()!.querySelector<HTMLButtonElement>('[data-test="cite-open"]')!.click()
    await flushPromises()
    expect(wrapper.emitted('cite')).toEqual([[1]])
    wrapper.unmount()
  })

  it('closes after the pointer leaves both the marker and the popover', async () => {
    const wrapper = mountAnswer()
    const marker = wrapper.find('sup.cite')

    await marker.trigger('mouseover')
    await flushPromises()
    await marker.trigger('mouseout', { relatedTarget: document.body })
    vi.advanceTimersByTime(500)
    await flushPromises()

    expect(preview()).toBeNull()
    expect(wrapper.emitted('cite')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('AnswerContent rich blocks', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('renders markdown tables via AnswerTable', () => {
    const wrapper = mount(AnswerContent, {
      props: {
        content: `| 车间 | 产量 |
| --- | --- |
| A | 10 |
| B | 20 |`,
        citations: [],
      },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.find('[data-test="answer-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="table-chart-toggle"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('车间')
    expect(wrapper.text()).toContain('产量')
    wrapper.unmount()
  })
})
