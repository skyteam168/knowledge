import { computed, ref, type Ref } from 'vue'
import { completeUpload, createUpload, putToStorage, uploadDirect } from '@/api/knowledge'
import { toHttpError } from '@/api/http'
import type { KbDocument } from '@/api/types'
import { t } from '@/i18n'
import { canHashInBrowser, isAcceptedFile, sha256Hex } from '@/utils/file'

export type UploadState =
  'pending' | 'hashing' | 'uploading' | 'completing' | 'done' | 'duplicate' | 'error'

export interface UploadTask {
  uid: number
  file: File
  state: UploadState
  percent: number
  message: string
  document: KbDocument | null
}

const CONCURRENCY = 3
let nextUid = 1

function resultMessage(result: { duplicate: boolean; new_version?: boolean }): string {
  if (result.duplicate) return t('knowledge.upload.duplicateExists')
  return result.new_version ? t('knowledge.upload.newVersion') : ''
}

export function useDocumentUpload(kbId: Ref<string>, onFinished?: (task: UploadTask) => void) {
  const tasks = ref<UploadTask[]>([])
  const running = ref(0)
  const busy = computed(() => tasks.value.some((t) => !isSettled(t.state)))

  function isSettled(state: UploadState): boolean {
    return state === 'done' || state === 'duplicate' || state === 'error'
  }

  function update(uid: number, patch: Partial<UploadTask>): void {
    const task = tasks.value.find((t) => t.uid === uid)
    if (task) Object.assign(task, patch)
  }

  async function run(task: UploadTask): Promise<void> {
    const { uid, file } = task
    try {
      if (!canHashInBrowser()) {
        update(uid, { state: 'uploading', percent: 0 })
        const result = await uploadDirect(kbId.value, file, (p) => update(uid, { percent: p }))
        update(uid, {
          state: result.duplicate ? 'duplicate' : 'done',
          percent: 100,
          document: result.document,
          message: resultMessage(result),
        })
        return
      }
      update(uid, { state: 'hashing', percent: 0 })
      const sha256 = await sha256Hex(file)
      const init = await createUpload(kbId.value, {
        filename: file.name,
        size_bytes: file.size,
        mime_type: file.type || null,
        sha256,
      })
      if (init.duplicate || !init.upload_url || !init.ticket) {
        update(uid, {
          state: 'duplicate',
          percent: 100,
          document: init.document,
          message: t('knowledge.upload.duplicateOf', {
            title: init.document?.title ?? t('knowledge.upload.exists'),
          }),
        })
        return
      }
      update(uid, { state: 'uploading' })
      await putToStorage(init.upload_url, file, (p) => update(uid, { percent: Math.min(p, 99) }))
      update(uid, { state: 'completing', percent: 99 })
      const result = await completeUpload(kbId.value, init.ticket)
      update(uid, {
        state: result.duplicate ? 'duplicate' : 'done',
        percent: 100,
        document: result.document,
        message: resultMessage(result),
      })
    } catch (error) {
      update(uid, { state: 'error', message: toHttpError(error).message })
    } finally {
      const finished = tasks.value.find((t) => t.uid === uid)
      if (finished) onFinished?.(finished)
    }
  }

  function pump(): void {
    while (running.value < CONCURRENCY) {
      const next = tasks.value.find((t) => t.state === 'pending')
      if (!next) return
      next.state = 'hashing'
      running.value += 1
      void run(next).finally(() => {
        running.value -= 1
        pump()
      })
    }
  }

  function add(files: File[]): void {
    for (const file of files) {
      const accepted = isAcceptedFile(file.name)
      tasks.value.push({
        uid: nextUid++,
        file,
        state: accepted ? 'pending' : 'error',
        percent: 0,
        message: accepted ? '' : t('knowledge.upload.unsupported'),
        document: null,
      })
    }
    pump()
  }

  function retry(uid: number): void {
    update(uid, { state: 'pending', percent: 0, message: '' })
    pump()
  }

  function clearSettled(): void {
    tasks.value = tasks.value.filter((t) => !isSettled(t.state))
  }

  return { tasks, busy, add, retry, clearSettled }
}
