<script setup lang="ts">
import { toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { UploadRawFile } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import {
  useDocumentUpload,
  type UploadState,
  type UploadTask,
} from '@/composables/useDocumentUpload'
import { ACCEPTED_EXTENSIONS, formatBytes } from '@/utils/file'

const props = defineProps<{ kbId: string }>()
const emit = defineEmits<{ uploaded: [task: UploadTask] }>()
const { t } = useI18n()

const { tasks, add, retry, clearSettled } = useDocumentUpload(toRef(props, 'kbId'), (task) => {
  if (task.state === 'done' || task.state === 'duplicate') emit('uploaded', task)
})

function stateLabel(state: UploadState): string {
  return t(`knowledge.upload.${state}`)
}

function onSelect(raw: UploadRawFile): boolean {
  add([raw])
  return false
}

function progressStatus(state: UploadState): '' | 'success' | 'exception' | 'warning' {
  if (state === 'done') return 'success'
  if (state === 'error') return 'exception'
  if (state === 'duplicate') return 'warning'
  return ''
}
</script>

<template>
  <div class="uploader">
    <el-upload
      drag
      multiple
      :show-file-list="false"
      :accept="ACCEPTED_EXTENSIONS.join(',')"
      :before-upload="onSelect"
      data-test="doc-upload"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <i18n-t keypath="knowledge.upload.dropHint" tag="div" class="el-upload__text">
        <template #action>
          <em>{{ t('knowledge.upload.clickToSelect') }}</em>
        </template>
      </i18n-t>
      <template #tip>
        <div class="el-upload__tip">
          {{ t('knowledge.upload.tip') }}
        </div>
      </template>
    </el-upload>

    <div v-if="tasks.length" class="tasks">
      <div class="tasks-header">
        <span>{{ t('knowledge.upload.queue') }}</span>
        <el-button link type="primary" @click="clearSettled">{{
          t('knowledge.upload.clearDone')
        }}</el-button>
      </div>
      <div v-for="task in tasks" :key="task.uid" class="task">
        <div class="task-line">
          <span class="task-name" :title="task.file.name">{{ task.file.name }}</span>
          <span class="task-size">{{ formatBytes(task.file.size) }}</span>
          <el-tag
            size="small"
            :type="progressStatus(task.state) === 'exception' ? 'danger' : 'info'"
          >
            {{ stateLabel(task.state) }}
          </el-tag>
          <el-button v-if="task.state === 'error'" link type="primary" @click="retry(task.uid)">
            {{ t('knowledge.upload.retry') }}
          </el-button>
        </div>
        <el-progress
          :percentage="task.percent"
          :status="progressStatus(task.state)"
          :stroke-width="6"
        />
        <div v-if="task.message" class="task-message">{{ task.message }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tasks {
  margin-top: 12px;
}
.tasks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
  margin-bottom: 4px;
}
.task {
  padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.task-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-size {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.task-message {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
