import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import VersionCompareDialog from '../VersionCompareDialog.vue'
import type { DocumentVersion, VersionCompare } from '@/api/types'

const compareVersions = vi.fn()
vi.mock('@/api/knowledge', () => ({
  compareVersions: (...args: unknown[]) => compareVersions(...args),
}))

function version(n: number): DocumentVersion {
  return {
    version: n,
    filename: '规范.md',
    mime_type: 'text/markdown',
    size_bytes: 10,
    sha256: `sha${n}`,
    restored_from: null,
    created_by: 'u1',
    created_by_name: 'Bob',
    created_at: '2026-10-20T00:00:00Z',
  }
}

const RESULT: VersionCompare = {
  base: version(1),
  target: version(2),
  available: true,
  same_file: false,
  added: 1,
  removed: 1,
  truncated: false,
  hunks: [
    [
      { op: 'equal', text: '# 工艺规范', old_no: 1, new_no: 1 },
      { op: 'del', text: '温度 180 度。', old_no: 2, new_no: null },
      { op: 'add', text: '温度 200 度。', old_no: null, new_no: 2 },
    ],
  ],
}

describe('VersionCompareDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    compareVersions.mockReset().mockResolvedValue(RESULT)
  })

  it('loads the chosen pair and renders added and removed lines', async () => {
    mount(VersionCompareDialog, {
      props: {
        docId: 'd1',
        versions: [version(2), version(1)],
        pair: [1, 2],
        protection: { watermark: true, copy_protect: true, download_permission: 'edit' },
      },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(compareVersions).toHaveBeenCalledWith('d1', 1, 2)
    const lines = [...document.querySelectorAll<HTMLElement>('[data-op]')]
    expect(lines.map((l) => l.dataset.op)).toEqual(['equal', 'del', 'add'])
    expect(lines[2].textContent).toContain('温度 200 度。')
    expect(document.querySelector('[data-test="watermark-layer"]')).not.toBeNull()
    expect(document.querySelector('[data-test="compare-stats"]')?.textContent).toContain('1')
  })
})
