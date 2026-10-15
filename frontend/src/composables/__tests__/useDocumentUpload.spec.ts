import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import type { KbDocument } from '@/api/types'

vi.mock('@/api/knowledge', () => ({
  createUpload: vi.fn(),
  completeUpload: vi.fn(),
  putToStorage: vi.fn(),
  uploadDirect: vi.fn(),
}))
vi.mock('@/utils/file', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/file')>()),
  canHashInBrowser: () => true,
  sha256Hex: vi.fn(async () => 'a'.repeat(64)),
}))
vi.mock('@/api/http', () => ({
  toHttpError: (e: unknown) => ({ message: e instanceof Error ? e.message : String(e) }),
}))

const api = await import('@/api/knowledge')
const { useDocumentUpload } = await import('@/composables/useDocumentUpload')

const doc = { id: 'd1', title: 'handbook' } as KbDocument

function file(name: string): File {
  return new File(['hello'], name, { type: 'text/plain' })
}

describe('useDocumentUpload', () => {
  beforeEach(() => vi.clearAllMocks())

  it('hashes, uploads to storage and completes', async () => {
    vi.mocked(api.createUpload).mockResolvedValue({
      duplicate: false,
      document: null,
      ticket: 't1',
      upload_url: 'http://minio/put',
      method: 'PUT',
      expires_in: 60,
    })
    vi.mocked(api.putToStorage).mockImplementation(async (_url, _file, onProgress) => {
      onProgress?.(50)
    })
    vi.mocked(api.completeUpload).mockResolvedValue({
      document: doc,
      duplicate: false,
      new_version: true,
    })
    const finished = vi.fn()
    const { tasks, add } = useDocumentUpload(ref('kb1'), finished)
    add([file('a.txt')])
    await flushPromises()

    expect(api.createUpload).toHaveBeenCalledWith('kb1', {
      filename: 'a.txt',
      size_bytes: 5,
      mime_type: 'text/plain',
      sha256: 'a'.repeat(64),
    })
    expect(api.completeUpload).toHaveBeenCalledWith('kb1', 't1')
    expect(tasks.value[0]).toMatchObject({ state: 'done', percent: 100, message: '已生成新版本' })
    expect(finished).toHaveBeenCalledOnce()
  })

  it('stops at duplicates without uploading', async () => {
    vi.mocked(api.createUpload).mockResolvedValue({
      duplicate: true,
      document: doc,
      ticket: null,
      upload_url: null,
      method: 'PUT',
      expires_in: null,
    })
    const { tasks, add } = useDocumentUpload(ref('kb1'))
    add([file('a.txt')])
    await flushPromises()
    expect(api.putToStorage).not.toHaveBeenCalled()
    expect(tasks.value[0]?.state).toBe('duplicate')
  })

  it('rejects unsupported files and reports errors', async () => {
    vi.mocked(api.createUpload).mockRejectedValue(new Error('boom'))
    const { tasks, add } = useDocumentUpload(ref('kb1'))
    add([file('tool.exe'), file('b.md')])
    await flushPromises()
    expect(tasks.value.map((t) => t.state)).toEqual(['error', 'error'])
    expect(tasks.value[0]?.message).toBe('不支持的文件类型')
    expect(tasks.value[1]?.message).toBe('boom')
    expect(api.createUpload).toHaveBeenCalledOnce()
  })
})
